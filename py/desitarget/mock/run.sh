export PATH=/global/homes/m/mjwilson/desi/E2E/desitarget/bin/:$PATH
export PYTHONPATH=/global/homes/m/mjwilson/desi/E2E/desitarget/py/:/global/homes/m/mjwilson/desi/E2E/desitarget/:/global/homes/m/mjwilson/desi/E2E/desitarget/py/desitarget/mock/aux:$PYTHONPATH

# [release, gmm];  
select_mock_targets -c /global/homes/m/mjwilson/desi/E2E/desitarget/py/desitarget/mock/data/select-mock-targets-nocontam.yaml --output_dir /global/cscratch1/sd/mjwilson/desi/E2E/desitarget/ -n 4 --survey main --healpixels 1 --no-spectra --nside 64 --no-spectra --overwrite --verbose --sampling release
