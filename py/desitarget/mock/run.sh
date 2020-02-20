export PATH=/global/homes/m/mjwilson/desi/E2E/desitarget/bin/:$PATH
export PYTHONPATH=/global/homes/m/mjwilson/desi/E2E/desitarget/py/:/global/homes/m/mjwilson/desi/E2E/desitarget/:$PYTHONPATH

# [release, gmm];  
select_mock_targets -c /global/homes/m/mjwilson/desi/E2E/desitarget/py/desitarget/mock/data/select-mock-targets-test.yaml --output_dir /global/cscratch1/sd/mjwilson/desi/E2E/desitarget/ -n 8 --survey main --nside 16 --no-spectra --overwrite --verbose --sampling gmm --healpixels 1 2 3 4 5 
