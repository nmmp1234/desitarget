# Licensed under a 3-clause BSD style license - see LICENSE.rst
# -*- coding: utf-8 -*-
"""
desitarget.mock.iospectra
=========================

Read mock catalogs and assign spectra.

"""
from __future__ import absolute_import, division, print_function

import os
import numpy as np
from glob import glob

import fitsio
from scipy import constants

from desiutil.brick import brickname as get_brickname_from_radec
from desimodel.footprint import radec2pix

from desiutil.log import get_logger, DEBUG
log = get_logger()

"""How to distribute 52 user bits of targetid.

Used to generate target IDs as combination of input file and row in input file.
Sets the maximum number of rows per input file for mocks using this scheme to
generate target IDs

"""
# First 32 bits are row
ENCODE_ROW_END     = 32
ENCODE_ROW_MASK    = 2**ENCODE_ROW_END - 2**0
ENCODE_ROW_MAX     = ENCODE_ROW_MASK
# Next 20 bits are file
ENCODE_FILE_END    = 52
ENCODE_FILE_MASK   = 2**ENCODE_FILE_END - 2**ENCODE_ROW_END
ENCODE_FILE_MAX    = ENCODE_FILE_MASK >> ENCODE_ROW_END

def encode_rownum_filenum(rownum, filenum):
    """Encodes row and file number in 52 packed bits.

    Parameters
    ----------
    rownum : int
        Row in input file.
    filenum : int
        File number in input file set.

    Returns
    -------
    encoded value(s) : int64 numpy.ndarray
        52 packed bits encoding row and file number.

    """
    assert(np.shape(rownum) == np.shape(filenum))
    assert(np.all(rownum  >= 0))
    assert(np.all(rownum  <= int(ENCODE_ROW_MAX)))
    assert(np.all(filenum >= 0))
    assert(np.all(filenum <= int(ENCODE_FILE_MAX)))

    # This should be a 64 bit integer.
    encoded_value = (np.asarray(filenum,dtype=np.uint64) << ENCODE_ROW_END) + np.asarray(rownum, dtype=np.uint64)

    # Note return signed
    return np.asarray(encoded_value, dtype=np.int64)

def decode_rownum_filenum(encoded_values):
    """Inverts encode_rownum_filenum to obtain row number and file number.

    Parameters
    ----------
    encoded_values(s) : int64 ndarray

    Returns
    -------
    filenum : str
        File number.
    rownum : int
        Row number.

    """
    filenum = (np.asarray(encoded_values,dtype=np.uint64) & ENCODE_FILE_MASK) >> ENCODE_ROW_END
    rownum  = (np.asarray(encoded_values,dtype=np.uint64) & ENCODE_ROW_MASK)
    return rownum, filenum

def make_mockid(objid, n_per_file):
    """
    Computes mockid from row and file IDs.

    Parameters
    ----------
    objid : int array
        Row identification number.
    n_per_file : int list
        Number of items per file that went into objid.

    Returns
    -------
    mockid : int array
        Encoded row and file ID.

    """
    n_files = len(n_per_file)
    n_obj = len(objid)

    n_p_file = np.array(n_per_file)
    n_per_file_cumsum = n_p_file.cumsum()

    filenum = np.zeros(n_obj, dtype='int64')
    for n in range(1, n_files):
        filenum[n_per_file_cumsum[n-1]:n_per_file_cumsum[n]] = n

    return encode_rownum_filenum(objid, filenum)

def mw_transmission(source_data, dust_dir=None):
    """Compute the grzW1W2 Galactic transmission for every object.
    
    Args:
        source_data : dict
            Input dictionary (read by read_mock_catalog) with coordinates. 
            
    Returns:
        source_data : dict
            Modified input dictionary with MW transmission included. 

    """
    from desitarget.mock import sfdmap

    if dust_dir is None:
        log.warning('DUST_DIR is a required input!')
        raise ValueError

    extcoeff = dict(G = 3.214, R = 2.165, Z = 1.221, W1 = 0.184, W2 = 0.113)
    source_data['EBV'] = sfdmap.ebv(source_data['RA'],
                                    source_data['DEC'],
                                    mapdir=dust_dir)

    for band in ('G', 'R', 'Z', 'W1', 'W2'):
        source_data['MW_TRANSMISSION_{}'.format(band)] = 10**(-0.4 * extcoeff[band] * source_data['EBV'])

def _sample_vdisp(data, mean=1.9, sigma=0.15, fracvdisp=(0.1, 1), rand=None, nside=128):
    """Choose a subset of velocity dispersions."""

    if rand is None:
        rand = np.random.RandomState()

    def _sample(nmodel=1):
        nvdisp = int(np.max( ( np.min( ( np.round(nmodel * fracvdisp[0]), fracvdisp[1] ) ), 1 ) ))
        vvdisp = 10**rand.normal(loc=mean, scale=sigma, size=nvdisp)
        return rand.choice(vvdisp, nmodel)

    # Hack! Assign the same velocity dispersion to galaxies in the same healpixel.
    nobj = len(data['RA'])
    vdisp = np.zeros(nobj)

    healpix = radec2pix(nside, data['RA'], data['DEC'])
    for pix in set(healpix):
        these = np.in1d(healpix, pix)
        vdisp[these] = _sample(nmodel=np.count_nonzero(these))

    return vdisp

def _default_wave(wavemin=None, wavemax=None, dw=0.2):
    """Generate a default wavelength vector for the output spectra.

    """
    from desimodel.io import load_throughput
    
    if wavemin is None:
        wavemin = load_throughput('b').wavemin - 10.0
    if wavemax is None:
        wavemax = load_throughput('z').wavemax + 10.0
            
    return np.arange(round(wavemin, 1), wavemax, dw)

class GaussianField(object):

    def __init__(self, bricksize=0.25, dust_dir=None):

        self.bricksize = bricksize
        self.mockdir_root = os.path.join( os.getenv('DESI_ROOT'), 'mocks', 'GaussianRandomField' )
        self.dust_dir = dust_dir

    def readmock(self, mockfile, target_name='', nside=8, healpixels=None, magcut=None):
        """Read the mock catalog.

        """
        if not os.path.isfile(mockfile):
            log.warning('Mock file {} not found!'.format(mockfile))
            raise IOError

        self.nside = nside
    
        # Read the whole DESI footprint.
        if healpixels is None:
            from desimodel.footprint import tiles2pix
            healpixels = tiles2pix(self.nside)

        # Read the ra,dec coordinates, generate mockid, and then restrict to the
        # desired healpixels.
        log.info('Reading {}'.format(mockfile))
        radec = fitsio.read(mockfile, columns=['RA', 'DEC'], upper=True, ext=1)
        nobj = len(radec)

        files = list()
        n_per_file = list()
        files.append(mockfile)
        n_per_file.append(nobj)

        objid = np.arange(nobj, dtype='i8')
        mockid = make_mockid(objid, n_per_file)

        log.info('Assigning healpix pixels with nside = {}'.format(self.nside))
        allpix = radec2pix(self.nside, radec['RA'], radec['DEC'])
        cut = np.where( np.in1d(allpix, healpixels)*1 )[0]

        nobj = len(cut)
        if nobj == 0:
            log.warning('No {}s in healpixels {}!'.format(target_name, healpixels))
            return dict()
        else:
            log.info('Trimmed to {} {}s in healpixel(s) {}'.format(nobj, target_name, healpixels))

        objid = objid[cut]
        mockid = mockid[cut]
        ra = radec['RA'][cut].astype('f8') % 360.0 # enforce 0 < ra < 360
        dec = radec['DEC'][cut].astype('f8')
        del radec

        # Assign bricknames.
        brickname = get_brickname_from_radec(ra, dec, bricksize=self.bricksize)

        # Add redshifts.
        if target_name.upper() == 'SKY':
            zz = np.zeros(len(ra))
            mag = np.zeros_like(zz) + 22 # placeholder
        else:
            data = fitsio.read(mockfile, columns=['Z_COSMO', 'DZ_RSD'], upper=True, ext=1, rows=cut)
            zz = (data['Z_COSMO'].astype('f8') + data['DZ_RSD'].astype('f8')).astype('f4')
            mag = np.zeros_like(zz) + 22 # placeholder
            
        # Pack into a basic dictionary.
        out = {'SOURCE_NAME': target_name, 'OBJID': objid, 'MOCKID': mockid,
               'RA': ra, 'DEC': dec, 'BRICKNAME': brickname, 
               'FILES': files, 'N_PER_FILE': n_per_file, 'Z': zz, 'MAG': mag}

        # Add MW transmission
        mw_transmission(out, dust_dir=self.dust_dir)

        return out

class SelectTargets(object):
    """Select various types of targets.

    """
    def __init__(self, **kwargs):
        
        #super(SelectTargets, self).__init__(**kwargs)

        from desitarget import (desi_mask, bgs_mask, mws_mask,
                                contam_mask, obsconditions)
        
        self.desi_mask = desi_mask
        self.bgs_mask = bgs_mask
        self.mws_mask = mws_mask
        self.contam_mask = contam_mask
        self.obsconditions = obsconditions

class QSOMaker(SelectTargets):

    def __init__(self, seed=None, normfilter='decam2014-z', **kwargs):

        from desisim.templates import SIMQSO

        super(QSOMaker, self).__init__(**kwargs)

        self.seed = seed
        self.rand = np.random.RandomState(self.seed)
        self.wave = _default_wave()

        self.objtype = 'QSO'
        self.normfilter = normfilter
        self.template_maker = SIMQSO(wave=self.wave, normfilter='decam2014-g')

        #self.default_mockfile = os.path.join( self.mockdir_root, 'v0.0.5', '{}.fits'.format(self.objtype) ) # default 

    def read(self, mockfile=None, mockformat='gaussianfield', dust_dir=None,
             healpixels=None, nside=8):
        """Read the mock file."""

        #if mockfile is None:
        #    mockfile = self.default_mockfile

        if mockformat == 'gaussianfield':
            MockReader = GaussianField(dust_dir=dust_dir)
        else:
            raise ValueError('Unrecognized mockformat {}!'.format(mockformat))

        data = MockReader.readmock(mockfile, target_name=self.objtype,
                                   healpixels=healpixels, nside=nside)
        
        if bool(data):
            data.update({
                'SEED': self.rand.randint(2**32, size=len(data['RA'])),
                'TRUESPECTYPE': self.objtype, 'TEMPLATETYPE': self.objtype,
                'TEMPLATESUBTYPE': ''
                })

        return data

    def make_spectra(self, data=None, index=None):
        """Generate tracer QSO spectra."""
        
        if index is None:
            index = np.arange(len(data['RA']))
        nobj = len(index)
            
        flux, wave, meta = self.template_maker.make_templates(
            nmodel=nobj, redshift=data['Z'][index], seed=self.seed,
            lyaforest=False, nocolorcuts=True)

        return flux, self.wave, meta

    def select_targets(self, targets, truth):
        """Select QSO targets."""
        from desitarget.cuts import isQSO_colors

        gflux, rflux, zflux, w1flux, w2flux = targets['FLUX_G'], targets['FLUX_R'], \
          targets['FLUX_Z'], targets['FLUX_W1'], targets['FLUX_W2']
          
        qso = isQSO_colors(gflux=gflux, rflux=rflux, zflux=zflux,
                           w1flux=w1flux, w2flux=w2flux, optical=True)

        targets['DESI_TARGET'] |= (qso != 0) * self.desi_mask.QSO
        targets['DESI_TARGET'] |= (qso != 0) * self.desi_mask.QSO_SOUTH
        targets['OBSCONDITIONS'] |= (qso != 0)  * self.obsconditions.mask(
            self.desi_mask.QSO.obsconditions)
        targets['OBSCONDITIONS'] |= (qso != 0)  * self.obsconditions.mask(
            self.desi_mask.QSO_SOUTH.obsconditions)

class LRGTree(object):
    """Build a KD Tree for LRGs."""
    def __init__(self, **kwargs):

        super(LRGTree, self).__init__(**kwargs)
        
        from scipy.spatial import cKDTree as KDTree
        from desisim.io import read_basis_templates

        self.meta = read_basis_templates(objtype='LRG', onlymeta=True)

        zobj = self.meta['Z'].data
        self.tree = KDTree(np.vstack((zobj)).T)

    def query(self, matrix):
        """Return the nearest template number based on the KD Tree."""

        dist, indx = self.tree.query(matrix)
        return dist, indx

class LRGMaker(LRGTree, SelectTargets):

    def __init__(self, seed=None, normfilter='decam2014-z', **kwargs):

        super(LRGMaker, self).__init__(**kwargs)

        from desisim.templates import LRG
        from desisim.io import read_basis_templates

        self.seed = seed
        self.rand = np.random.RandomState(self.seed)
        self.wave = _default_wave()

        self.objtype = 'LRG'
        self.normfilter = normfilter
        self.template_maker = LRG(wave=self.wave, normfilter=self.normfilter)

    def read(self, mockfile=None, mockformat='gaussianfield', dust_dir=None,
             healpixels=None, nside=8, nside_chunk=128):
        """Read the mock file."""

        if mockformat == 'gaussianfield':
            MockReader = GaussianField(dust_dir=dust_dir)
        else:
            raise ValueError('Unrecognized mockformat {}!'.format(mockformat))

        data = MockReader.readmock(mockfile, target_name=self.objtype,
                                   healpixels=healpixels, nside=nside)

        if bool(data):
            data.update({
                'SEED': self.rand.randint(2**32, size=len(data['RA'])),
                'TRUESPECTYPE': self.objtype, 'TEMPLATETYPE': self.objtype,
                'TEMPLATESUBTYPE': '',
                'VDISP': _sample_vdisp(data, mean=2.3, sigma=0.1, rand=self.rand, nside=nside_chunk),
                })

        return data

    def make_spectra(self, data=None, index=None):
        """Generate tracer QSO spectra."""
        from desisim.io import empty_metatable
        
        if index is None:
            index = np.arange(len(data['RA']))
        nobj = len(index)

        input_meta = empty_metatable(nmodel=len(index), objtype=self.objtype)
        for inkey, datakey in zip(('SEED', 'MAG', 'REDSHIFT', 'VDISP'),
                                  ('SEED', 'MAG', 'Z', 'VDISP')):
            input_meta[inkey] = data[datakey][index]

        import pdb ; pdb.set_trace()
        
        flux, wave, meta = self.template_maker.make_templates(
            nmodel=nobj, redshift=data['Z'][index], seed=self.seed,
            lyaforest=False, nocolorcuts=True)

        return flux, self.wave, meta

    def select_targets(self, targets, truth):
        """Select QSO targets."""
        from desitarget.cuts import isQSO_colors

        gflux, rflux, zflux, w1flux, w2flux = targets['FLUX_G'], targets['FLUX_R'], \
          targets['FLUX_Z'], targets['FLUX_W1'], targets['FLUX_W2']
          
        qso = isQSO_colors(gflux=gflux, rflux=rflux, zflux=zflux,
                           w1flux=w1flux, w2flux=w2flux, optical=True)

        targets['DESI_TARGET'] |= (qso != 0) * self.desi_mask.QSO
        targets['DESI_TARGET'] |= (qso != 0) * self.desi_mask.QSO_SOUTH
        targets['OBSCONDITIONS'] |= (qso != 0)  * self.obsconditions.mask(
            self.desi_mask.QSO.obsconditions)
        targets['OBSCONDITIONS'] |= (qso != 0)  * self.obsconditions.mask(
            self.desi_mask.QSO_SOUTH.obsconditions)

class SKYMaker(SelectTargets):

    def __init__(self, seed=None, **kwargs):

        super(SKYMaker, self).__init__(**kwargs)

        self.seed = seed
        self.rand = np.random.RandomState(self.seed)
        self.wave = _default_wave()

        self.objtype = 'SKY'
        #self.default_mockfile = os.path.join( self.mockdir_root, 'v0.0.1', '2048', 'random.fits' ) # default 

    def read(self, mockfile=None, mockformat='gaussianfield', dust_dir=None,
             healpixels=None, nside=8):
        """Read the mock file."""

        if mockformat == 'gaussianfield':
            MockReader = GaussianField(dust_dir=dust_dir)
        else:
            raise ValueError('Unrecognized mockformat {}!'.format(mockformat))

        data = MockReader.readmock(mockfile, target_name=self.objtype,
                                   healpixels=healpixels, nside=nside)
        
        if bool(data):
            data.update({
                'SEED': self.rand.randint(2**32, size=len(data['RA'])),
                'TRUESPECTYPE': self.objtype, 'TEMPLATETYPE': self.objtype,
                 'TEMPLATESUBTYPE': ''
                })

        return data

    def make_spectra(self, data=None, index=None):
        """Generate SKY spectra."""
        from desisim.io import empty_metatable
        
        if index is None:
            index = np.arange(len(data['RA']))
        nobj = len(index)
            
        meta = empty_metatable(nmodel=nobj, objtype=self.objtype)
        for inkey, datakey in zip(('SEED', 'REDSHIFT'),
                                  ('SEED', 'Z')):
            meta[inkey] = data[datakey][index]
        flux = np.zeros((nobj, len(self.wave)), dtype='i1')

        return flux, self.wave, meta

    def select_targets(self, targets, truth):
        """Select SKY targets."""

        targets['DESI_TARGET'] |= self.desi_mask.mask('SKY')
        targets['OBSCONDITIONS'] |= self.obsconditions.mask(
            self.desi_mask.SKY.obsconditions)
