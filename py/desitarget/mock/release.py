from __future__ import (absolute_import, division, print_function, unicode_literals)

import os
import numpy as np
from glob import glob
from pkg_resources import resource_filename

import fitsio
import healpy as hp

from desiutil import brick
from desimodel.io import load_pixweight
from desimodel import footprint
from desitarget import cuts
from desisim.io import empty_metatable
from functools import lru_cache
from astropy.table import Table, vstack, Column
from desitarget import randoms
from desitarget.randoms import dr8_quantities_at_positions_in_a_brick

from desiutil.log import get_logger, DEBUG
log = get_logger(timestamp=True)

try:
    from scipy import constants
    C_LIGHT = constants.c/1000.0
except TypeError: # This can happen during documentation builds.                                                                                                                                                                        
    C_LIGHT = 299792458.0/1000.0

def flux2mag(flux):
    mag            = -2.5 * np.log10(flux * (flux>0) + 0.001*(flux<=0)) + 22.5
    mag[(flux<=0)] = 0.

    return  mag

def prep_releasepixel(release=8, ver='0.32.0', main='main', resolve='resolve', time='dark', hp=32):
    from   astropy.table      import Table, vstack
    from   desitarget.targets import desi_mask, bgs_mask, mws_mask

    log.info('Preparing release healpixel: {} ({})'.format(hp, time))

    # E.g. /project/projectdirs/desi/target/catalogs/dr8/0.32.0/targets/main/resolve/bright/targets-dr8-hp-14.fits                                                                                                                      
    fpath   = '/project/projectdirs/desi/target/catalogs/dr{}/{}/targets/{}/{}/{}/targets-dr{}-hp-{}.fits'.format(release, ver, main, resolve, time, release, str(hp))

    fits    = fitsio.FITS(fpath)
    _       = fits[1].read()
    cols    = fits[1].get_colnames()

    release = Table(_)

    # Append colors.                                                                                                                                                                                                                    
    gmag    = flux2mag(release['FLUX_G']  / release['MW_TRANSMISSION_G'])
    rmag    = flux2mag(release['FLUX_R']  / release['MW_TRANSMISSION_R'])
    zmag    = flux2mag(release['FLUX_Z']  / release['MW_TRANSMISSION_Z'])
    W1mag   = flux2mag(release['FLUX_W1'] / release['MW_TRANSMISSION_W1'])
    W2mag   = flux2mag(release['FLUX_W2'] / release['MW_TRANSMISSION_W2'])

    gr      = gmag - rmag
    rz      = rmag - zmag
    zW1     = zmag - W1mag
    W1W2    = W1mag - W2mag

    for col, key in zip([gr, rz, zW1, W1W2], ['GR', 'RZ', 'ZW1', 'W1W2']):
        release[key] = col

    # https://github.com/desihub/desitarget/blob/a64ed3adb1e38bbe23bf536e021153ada11bb8ac/doc/nb/target-selection-bits-and-bitmasks.ipynb                                                                                               
    isBGS   = (release["DESI_TARGET"] & desi_mask["BGS_ANY"]) != 0
    isLRG   = (release["DESI_TARGET"] & desi_mask["LRG"])     != 0
    isELG   = (release["DESI_TARGET"] & desi_mask["ELG"])     != 0
    isQSO   = (release["DESI_TARGET"] & desi_mask["QSO"])     != 0

    release['SAMPLE']        = np.zeros(len(release['FLUX_G']), dtype='S4')

    release['SAMPLE'][isBGS] = b'BGS'
    release['SAMPLE'][isLRG] = b'LRG'
    release['SAMPLE'][isELG] = b'ELG'
    release['SAMPLE'][isQSO] = b'QSO'

    # Append MAG and MAGFILTER.                                                                                                                                                                                                         
    issouth = release['PHOTSYS'] == b'S'

    release['MAG']           = np.zeros(len(release['FLUX_G']), dtype='f4')
    release['MAGFILTER']     = np.zeros(len(release['FLUX_G']), dtype='S15')

    release['MAG'][ isLRG &  issouth] = zmag[ isLRG &  issouth]
    release['MAG'][~isLRG &  issouth] = rmag[~isLRG &  issouth]

    release['MAG'][ isLRG & ~issouth] = zmag[ isLRG & ~issouth]
    release['MAG'][~isLRG & ~issouth] = rmag[~isLRG & ~issouth]

    ##                                                                                                                                                                                                                                  
    release['MAGFILTER'][ isLRG &  issouth] = np.repeat('decam2014-z', np.count_nonzero( isLRG & issouth))
    release['MAGFILTER'][~isLRG &  issouth] = np.repeat('decam2014-r', np.count_nonzero(~isLRG & issouth))

    release['MAGFILTER'][ isLRG & ~issouth] = np.repeat('MzLS-z', np.count_nonzero( isLRG & ~issouth))
    release['MAGFILTER'][~isLRG & ~issouth] = np.repeat('BASS-r', np.count_nonzero(~isLRG & ~issouth))

    release['TYPE'] = release['MORPHTYPE']

    del  release['RA']
    del  release['DEC']

    # for key in release.colnames:                                                                                                                                                                                                      
    #    if key not in tokeep:                                                                                                                                                                                                          
    #        del  release[key]                                                                                                                                                                                                          

    log.info('Finished preparing release healpixel: {}'.format(hp))

    return  release


@lru_cache(maxsize=1)
def prep_release(npix=1, seed=0):
    from   astropy.table  import  Table, vstack

    '''                                                                                                                                                                                                                                
    Prep npix worth of pixels from a given release from both                                                                                                                                                                           
    bright and dark.                                                                                                                                                                                                                                                                                                                                                                                                                                                          
    Parameters                                                                                                                                                                                                                        
    ----------                                                                                                                                                                                                                          
    npix : :class:`int`                                                                                                                                                                                                              
        Number of pixels to prep. for both dark and bright.                                                                                                                                                                            

    Returns                                                                                                                                                                                                                            
    -------                                                                                                                                                                                                                             
    targets : :class:`astropy.table.Table`                                                                                                                                                                                             
        Targets table to be selected from.                                                                                                                                                                                                 '''

    cnt   = 0

    hps   = np.arange(0, 34, 1)
    rand  = np.random.RandomState(seed)

    np.random.shuffle(hps)

    release = None
    
    while cnt < npix:
        cnt += 1

        if release == None:
            drelease = prep_releasepixel(hp = hps[cnt], time='dark')
            brelease = prep_releasepixel(hp = hps[cnt], time='bright')

            # ignore repeated tids across b and d time.                                                                                                                                                                                 
            release  = vstack([drelease, brelease])

        else:
            release  = vstack([release, prep_releasepixel(hp = hps[cnt], time='dark'), prep_releasepixel(hp = hps[cnt], time='bright')])
        
    return  release

if __name__ == '__main__':
    prep_release()

    print('\n\nDone.\n\n')
