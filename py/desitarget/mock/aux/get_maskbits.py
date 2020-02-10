from desitarget import randoms


def maskbit_at_positions_in_a_brick(ras, decs, brickname, drdir, aprad=0.75):
    """Observational quantities (per-band) at positions in a Legacy Surveys brick.
    Parameters
    ----------
    ras : :class:`~numpy.array`
        Right Ascensions of interest (degrees).
    decs : :class:`~numpy.array`
        Declinations of interest (degrees).
    brickname : :class:`str`
        Name of brick which contains RA/Dec positions, e.g., '1351p320'.
    drdir : :class:`str`
       The root directory pointing to a Data Release from the Legacy Surveys
       e.g. /global/project/projectdirs/cosmo/data/legacysurvey/dr7.
    aprad : :class:`float`, optional, defaults to 0.75
        Radii in arcsec of aperture for which to derive sky fluxes
        defaults to the DESI fiber radius.
    Returns
    -------
    :class:`dictionary`
      Only returns the maskbits for efficiency
    Notes
    -----
        - First version copied shamelessly from dr8_quantities_at_positions_in_a_brick.
    """
    
    # ADM guard against too low a density of random locations.
    npts = len(ras)
    if npts == 0:
        msg = 'brick {} is empty. Increase the density of random points!'.format(brickname)
        log.critical(msg)
        raise ValueError(msg)

        
    # ADM determine whether the coadd files have extension .gz or .fz based on the DR directory.
    extn, extn_nb = randoms.dr_extension(drdir)

    # ADM the output dictionary.
    qdict = {}

    # as a speed up, we assume all images in different filters for the brick have the same WCS
    # -> if we have read it once (iswcs=True), we use this info
    iswcs = False
    # ADM this will store the instrument name the first time we touch the wcs
    instrum = None

    rootdir = os.path.join(drdir, 'coadd', brickname[:3], brickname)
    fileform = os.path.join(rootdir, 'legacysurvey-{}-{}-{}.fits.{}')
    
    
    # ADM add the MASKBITS and WISEMASK information.
    fn = os.path.join(rootdir,
                      'legacysurvey-{}-maskbits.fits.{}'.format(brickname, extn))
    # ADM only process the WCS if there's a file for this filter.
    mnames = zip([extn_nb],
                 ['maskbits'],
                 ['>i2'])
    for mextn, mout, mform in mnames:
        if os.path.exists(fn):
            img = fits.open(fn)[mextn]
            # ADM use the WCS for the per-filter quantities if it exists.
            if not iswcs:
                # ADM store the instrument name, if it isn't yet stored.
                #print(img.header.keys)
                #instrum = img.header["INSTRUME"].lower().strip()
                w = WCS(img.header)
                x, y = w.all_world2pix(ras, decs, 0)
                iswcs = True
            # ADM add the maskbits to the dictionary.
            qdict[mout] = img.data[y.astype("int"), x.astype("int")]
        else:
            # ADM if no files are found, populate with zeros.
            qdict[mout] = np.zeros(npts, dtype=mform)
            # ADM if there was no maskbits file, populate with BAILOUT.
            if mout == 'maskbits':
                qdict[mout] |= 2**10

    if(0):
        # ADM populate the photometric system in the quantity dictionary.
        if instrum is None:
            # ADM don't count bricks where we never read a file header.
            return
        elif instrum == 'decam':
            qdict['photsys'] = np.array([b"S" for x in range(npts)], dtype='|S1')
        else:
            qdict['photsys'] = np.array([b"N" for x in range(npts)], dtype='|S1')
    #    log.info('Recorded quantities for each point in brick {}...t = {:.1f}s'
    #                  .format(brickname,time()-start))

    return qdict
