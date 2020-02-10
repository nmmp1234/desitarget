export PATH=/global/homes/m/mjwilson/desi/E2E/desitarget/bin/:$PATH
export PYTHONPATH=/global/homes/m/mjwilson/desi/E2E/desitarget/py/:/global/homes/m/mjwilson/desi/E2E/desitarget/:$PYTHONPATH

select_mock_targets -c /global/homes/m/mjwilson/desi/E2E/desitarget/py/desitarget/mock/data/select-mock-targets.yaml --output_dir /global/homes/m/mjwilson/desi/E2E/desitarget/scratch -n 4 --survey main --healpixels 1 --no-spectra --nside 256 --no-spectra --overwrite --verbose
