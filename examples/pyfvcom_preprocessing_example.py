
# coding: utf-8

# This notebook shows how to create FVCOM forcing data for an unstructured grid.
#
# We need an SMS unstructured grid (`.2dm` file) in which we have defined some nodestrings to act as open boundaries.
#
# We'll be making the following files:
#
# - casename_grd.dat
# - casename_dep.dat
# - sigma.dat
# - casename_obc.dat
# - casename_cor.dat
# - casename_elevtide.nc
#

# In[1]:

# get_ipython().magic('matplotlib inline')
# 20240722

# In[2]:

from datetime import datetime
import PyFVCOM as pf
def pro_name_list():
    start=datetime.strptime('2024-04-01', '%Y-%m-%d')
    end=datetime.strptime('2024-05-01', '%Y-%m-%d')
    nml_obc=pf.preproc.ModelNameList(casename='zyj')
    nml_obc.update('NML_CASE', 'START_DATE','2024-04-01 00:00:00')
    nml_obc.update('NML_CASE', 'END_DATE','2024-05-01 00:00:00')
    nml_obc.update('NML_NETCDF_SURFACE', 'NCSF_FIRST_OUT','zyj')
    # nml_obc.config['START_DATE']=start
    # nml_obc.config['END_DATE']=end
    print(nml_obc.value('NML_CASE', 'START_DATE'))
    print(nml_obc.value('NML_CASE', 'END_DATE'))
    nml_obc.write_model_namelist('estuary.nml')

def pro_file_make():
    filename=r"G:\zyj20240712\step02202406251531.2dm"
# In[4]:
# Define a start, end and sampling interval for the tidal data
    start = datetime.strptime('2024-04-01', '%Y-%m-%d')
    end = datetime.strptime('2024-05-01', '%Y-%m-%d')
    interval = 1 / 24  # 1 hourly in units of days
    model = pf.preproc.Model(start, end, filename, sampling=interval,
                         native_coordinates='spherical', zone='35',debug=True)
    model.add_bed_roughness(0.027)

# In[5]:

# Define everything we need for the open boundaries.

# We need the TPXO data to predict tides at the boundary. Get that from here:
#    ftp://ftp.oce.orst.edu/dist/tides/Global/tpxo9_netcdf.tar.gz
# and extract its contents in the PyFVCOM/examples directory.
    tpxo_harmonics = r'E:\fes2014\fes2014b_elevations\ocean_tide'
    tpxo_harmonics = r'D:\zyj\FES2014\fes2014_elevations_and_load\fes2014b_elevations_extrapolated\ocean_tide_extrapolated\ocean_tide_extrapolated'
    constituents = ['SA', 'SSA','Q1',"O1","P1","K1","N2","M2",'S2','K2','M4','MS4','M6']
    for boundary in model.open_boundaries:
        # Create a 5km sponge layer for all open boundaries.
        boundary.add_sponge_layer(5000, 0.001)
        # Set the type of open boundary we've got.
        boundary.add_type(1)  # prescribed surface elevation
        # And add some tidal data.
        # boundary.add_tpxo_tides(tpxo_harmonics, predict='zeta', constituents=constituents, interval=interval)
        boundary.add_fes2014_tides(tpxo_harmonics, predict='zeta', constituents=constituents, interval=interval)

    # In[6]:

    # Make a vertical grid with 21 uniform levels
    model.sigma.type = 'uniform'
    model.dims.levels = 21


    # In[7]:

    # Write out the files for FVCOM.
    casenmae='zyj'
    # model.write_grid(casenmae+'_grd.dat', depth_file=casenmae+'_dep.dat')
    # model.write_sponge(casenmae+'_spg.dat')
    # model.write_obc(casenmae+'_obc.dat')
    # model.write_coriolis(casenmae+'_cor.dat')
    # model.write_sigma('sigma.dat')
    # model.write_tides(casenmae+'_elevtide.nc')
    #
    model.write_bed_roughness(casenmae+'_brf.nc')
    #

    # In[9]:

    # Let's have a look at the grid we've just worked on.
    mesh = pf.read.Domain('estuary.2dm', native_coordinates='spherical', zone='53')
    domain = pf.plot.Plotter(mesh, figsize=(20, 10), tick_inc=(0.1, 0.05), cb_label='Depth (m)')
    domain.plot_field(-mesh.grid.h)
    for boundary in model.open_boundaries:
        domain.axes.plot(*domain.m(boundary.grid.lon, boundary.grid.lat), 'ro')

if __name__ == "__main__":
    pro_file_make()