"""
Tools to prepare data for an FVCOM run.

A very gradual port of the most used functions from the MATLAB toolbox:
    https://github.com/pwcazenave/fvcom-toolbox/tree/master/fvcom_prepro/

Author(s):

Mike Bedington (Plymouth Marine Laboratory)
Pierre Cazenave (Plymouth Marine Laboratory)

"""

import numpy as np
import multiprocessing as mp

from netCDF4 import Dataset, date2num, num2date
from scipy.interpolate import RegularGridInterpolator
from dateutil.relativedelta import relativedelta
from datetime import datetime
from functools import partial
from warnings import warn

from PyFVCOM.grid import *
from PyFVCOM.coordinate import *


def interp_sst_assimilation(domain, sst_dir, year, serial=False, pool_size=None, noisy=False):
    """
    Interpolate SST data from remote sensing data onto the supplied model
    grid.

    Parameters
    ----------
    domain : PyFVCOM.grid.Domain
        Model domain object.
    sst_dir : str
        Path to directory containing the SST data. Assumes there are directories per year within this directory.
    year : int
        Tear for which to generate SST data
    serial : bool, optional
        Run in serial rather than parallel. Defaults to parallel.
    pool_size : int, optional
        Specify number of processes for parallel run. By default it uses all available.
    noisy : bool, optional
        Set to True to enable some sort of progress output. Defaults to False.

    Returns
    -------
    sst : np.ndarray
        Interpolated SST time series for the supplied domain.
    date_list : np.ndarray
        List of python datetimes for the corresponding SST data.

    Example
    -------
    >>> sst_dir = '/home/mbe/Data/SST_data/2006/'
    >>> domain = Domain('/home/mbe/Models/FVCOM/tamar/tamar_v2_grd.dat',
    >>>     native_coordinates='cartesian', zone='30N')
    >>> sst, dates = interp_sst_assimilation(domain, sst_dir, 2006, serial=False, pool_size=20)
    >>> # Save to netCDF
    >>> write_sstgrd('casename_sstgrd.nc', domain, sst, dates)

    Notes
    -----
    - Based on https://github.com/pwcazenave/fvcom-toolbox/tree/master/fvcom_prepro/interp_sst_assimilation.m.

    """

    # SST files. Try to prepend the end of the previous year and the start of the next year.
    sst_files = [os.path.join(sst_dir, str(year - 1), sorted(os.listdir(os.path.join(sst_dir, str(year - 1))))[-1])]
    sst_files += [os.path.join(sst_dir, str(year), i) for i in os.listdir(os.path.join(sst_dir, str(year)))]
    sst_files += [os.path.join(sst_dir, str(year + 1), sorted(os.listdir(os.path.join(sst_dir, str(year + 1))))[0])]

    if noisy:
        print('To do:\n{}'.format('|' * len(sst_files)), flush=True)

    # Read SST data files and interpolate each to the FVCOM mesh
    lonlat = np.array((domain.grid.lon, domain.grid.lat))

    if serial:
        results = []
        for sst_file in sst_files:
            results.append(_inter_sst_worker(lonlat, sst_file, noisy))
    else:
        if not pool_size:
            pool = mp.Pool()
        else:
            pool = mp.Pool(pool_size)
        part_func = partial(_inter_sst_worker, lonlat, noisy=noisy)
        results = pool.map(part_func, sst_files)
        pool.close()

    # Sort data and prepare date lists
    dates = np.empty(len(results)).astype(datetime)
    sst = np.empty((len(results), domain.dims.node))
    for i, result in enumerate(results):
        dates[i] = result[0][0] + relativedelta(hours=12)  # FVCOM wants times at midday whislt the data are a midnight
        sst[i, :] = result[1]

    return sst, dates


def _inter_sst_worker(fvcom_ll, sst_file, noisy=False):
    """ Multiprocessing worker function for the SST interpolation. """
    if noisy:
        print('.', end='', flush=True)
    with Dataset(sst_file, 'r') as sst_file_nc:
        sst_eo = np.squeeze(sst_file_nc.variables['analysed_sst'][:]) - 273.15  # Kelvin to Celsius
        mask = sst_file_nc.variables['mask']
        sst_eo[mask != 1] = np.nan

        sst_lon = sst_file_nc.variables['lon'][:]
        sst_lat = sst_file_nc.variables['lat'][:]

        ft = RegularGridInterpolator((sst_lon, sst_lat), sst_eo.T, method='nearest', fill_value=None)
        interp_sst = ft(np.asarray(fvcom_ll).T)

        time_out_dt = num2date(sst_file_nc.variables['time'][:], units=sst_file_nc.variables['time'].units)

    return time_out_dt, interp_sst


class WriteForcing:
    """ Create an FVCOM netCDF input file. """

    def __init__(self, filename, dimensions, global_attributes=None, **kwargs):
        """ Create a netCDF file.

        Parameters
        ----------
        filename : str, pathlib.Path
            Output netCDF path.
        dimensions : dict
            Dictionary of dimension names and sizes.
        global_attributes : dict, optional
            Global attributes to add to the netCDF file.
        Remaining arguments are passed to netCDF4.Dataset.

        Returns
        -------
        nc : netCDF4.Dataset
            The netCDF file object.

        """

        self.nc = Dataset(str(filename), 'w', **kwargs)

        for dimension in dimensions:
            self.nc.createDimension(dimension, dimensions[dimension])

        for attribute in global_attributes:
            setattr(self.nc, attribute, global_attributes[attribute])

    def add_variable(self, name, data, dimensions, attributes=None, format='f4', ncopts={}):
        """
        Create a `name' variable with the given `attributes' and `data'.

        Parameters
        ----------
        name : str
            Variable name to add.
        data : np.ndararay, list, float, str
            Data to add to the netCDF file object.
        dimensions : list, tuple
            List of dimension names to apply to the new variable.
        attributes : dict, optional
            Attributes to add to the netCDF variable object.
        format : str, optional
            Data format for the new variable. Defaults to 'f4' (float32).
        ncopts : dict
            Dictionary of options to use when creating the netCDF variables.

        """

        setattr(self, name, self.nc.createVariable(name, format, dimensions), **ncopts)
        for attribute in attributes:
            setattr(getattr(self, name), attribute, attributes[attribute])

        setattr(getattr(self, name), data)

    def close(self):
        """ Tidy up the netCDF file handle. """
        self.nc.close()


def write_sstgrd(output_file, domain, data, time, ncopts={'zlib': True, 'complevel': 7}, **kwargs):
    """
    Generate a sea surface temperature data assimilation file for the given FVCOM domain.

    Parameters
    ----------
    output_file : str, pathlib.Path
        File to which to write SST data.
    domain : PyFVCOM.grid.Domain
        The model domain.
    data : np.ndarray
        The data to write ([time, node]).
    time : np.ndarray
        The time series for the data as datetime objects.
    ncopts : dict
        Dictionary of options to use when creating the netCDF variables. Defaults to compression on.

    Remaining arguments are passed to WriteForcing.
    """

    globals = {'year': time[0].year,
               'title': 'FVCOM SST 1km merged product File',
               'institution': 'Plymouth Marine Laboratory',
               'source': 'FVCOM grid (unstructured) surface forcing',
               'history': 'File created using PyFVCOM',
               'references': 'http://fvcom.smast.umassd.edu, http://codfish.smast.umassd.edu',
               'Conventions': 'CF-1.0',
               'CoordinateProjection': 'init=WGS84'}
    dims = {'nele': domain.dims.nele, 'node': domain.dims.node, 'time': 0, 'DateStrLen': 26, 'three': 3}

    with WriteForcing(output_file, dims, global_attributes=globals, clobber=True, format='NETCDF4', **kwargs) as sstgrd:
        # Add the variables.
        atts = {'long_name': 'nodel longitude', 'units': 'degrees_east'}
        sstgrd.add_variable('lon', domain.lon, ['node'], attributes=atts, ncopts=ncopts)
        atts = {'long_name': 'nodel latitude', 'units': 'degrees_north'}
        sstgrd.add_variable('lat', domain.lat, ['node'], attributes=atts, ncopts=ncopts)
        atts = {'units': 'days since 1858-11-17 00:00:00',
                'delta_t': '0000-00-00 01:00:00',
                'format': 'modified julian day (MJD)',
                'time_zone': 'UTC'}
        sstgrd.add_variable('time', date2num(time, units='days since 1858-11-17 00:00:00'),
                            ['time'], attributes=atts, ncopts=ncopts)
        atts = {'long_name': 'Calendar Date',
                'format': 'String: Calendar Time',
                'time_zone': 'UTC'}
        sstgrd.add_variable('Times', [t.strftime('%Y-%m-%dT%H:%M:%S.%f') for t in time],
                            ['time', 'DateStrLen'], format='c', attributes=atts, ncopts=ncopts)
        atts = {'long_name': 'sea surface Temperature',
                'units': 'Celsius Degree',
                'grid': 'fvcom_grid',
                'type': 'data'}
        sstgrd.add_variable('sst', data, ['node'], attributes=atts, ncopts=ncopts)


def add_open_boundaries(domain, obcfile, reload=False):
    """

    Parameters
    ----------
    domain : PyFVCOM.grid.Domain
        Model domain object.
    obcfile : str, pathlib.Path
        FVCOM open boundary specification file.
    reload : bool
        Set to True to overwrite any automatically or already loaded open boundary nodes. Defaults to False.

    """
    if np.any(domain.obc_nodes) and np.any(domain.types) and reload:
        # We've already got some, so warn and return.
        warn('Open boundary nodes already loaded and reload set to False.')
        return
    else:
        domain.nodestrings, domain.types, _ = read_fvcom_obc(obcfile)


def add_sponge_layer(domain, radius=None):
    """ Add a sponge layer. """
    pass


def add_grid_metrics(self):
    """ Calculate grid metrics. """
    pass


def add_tpxo_tides(domain, interval=1):
    """
    Add TPXO tides at the open boundary nodes.

    Parameters
    ----------
    domain : PyFVCOM.grid.Domain
        Model domain object.
    interval : float
        Interval in time at which to generate predicted tides.

    """
    pass


def add_rivers(domain, positions):
    """
    Add river nodes closest to the given locations.

    Parameters
    ----------
    domain : PyFVCOM.grid.Domain
        Model domain object.
    positions : np.ndarray
        Positions (in longitude/latitude).

    """
    pass


def add_probes(domain, positions):
    """
    Generate probe locations closest to the given locations.

    Parameters
    ----------
    domain : PyFVCOM.grid.Domain
        Model domain object.
    positions : np.ndarray
        Positions (in longitude/latitude).

    """
    pass
