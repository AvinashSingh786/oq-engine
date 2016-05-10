# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2012-2016 GEM Foundation
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>.

"""
Module :mod:`~openquake.hazardlib.calc.gmf` exports
:func:`ground_motion_fields`.
"""
import collections

import numpy
import scipy.stats

from openquake.baselib.python3compat import zip
from openquake.hazardlib.const import StdDev
from openquake.hazardlib.calc import filters
from openquake.hazardlib.gsim.base import ContextMaker
from openquake.hazardlib.imt import from_string

U8 = numpy.uint8
U16 = numpy.uint16
U32 = numpy.uint32
F32 = numpy.float32

gmv_dt = numpy.dtype([('sid', U16), ('eid', U32), ('rlzi', U16),
                      ('imti', U8), ('gmv', F32)])


class CorrelationButNoInterIntraStdDevs(Exception):
    def __init__(self, corr, gsim):
        self.corr = corr
        self.gsim = gsim

    def __str__(self):
        return '''\
You cannot use the correlation model %s with the GSIM %s, \
that defines only the total standard deviation. If you want to use a \
correlation model you have to select a GMPE that provides the inter and \
intra event standard deviations.''' % (
            self.corr.__class__.__name__, self.gsim.__class__.__name__)


class GmfComputer(object):
    """
    Given an earthquake rupture, the ground motion field computer computes
    ground shaking over a set of sites, by randomly sampling a ground
    shaking intensity model.

    :param :class:`openquake.hazardlib.source.rupture.Rupture` rupture:
        Rupture to calculate ground motion fields radiated from.

    :param :class:`openquake.hazardlib.site.SiteCollection` sites:
        Sites of interest to calculate GMFs.

    :param imts:
        a sorted list of Intensity Measure Type strings

    :param truncation_level:
        Float, number of standard deviations for truncation of the intensity
        distribution, or ``None``.

    :param correlation_model:
        Instance of correlation model object. See
        :mod:`openquake.hazardlib.correlation`. Can be ``None``, in which
        case non-correlated ground motion fields are calculated.
        Correlation model is not used if ``truncation_level`` is zero.
    """
    def __init__(self, rupture, sites, imts, gsims,
                 truncation_level=None, correlation_model=None):
        assert sites, sites
        self.rupture = rupture
        self.sites = sites
        self.imts = [from_string(imt) for imt in imts]
        self.gsims = gsims
        self.truncation_level = truncation_level
        self.correlation_model = correlation_model
        self.ctx = ContextMaker(gsims).make_contexts(sites, rupture)

    def _compute(self, seed, gsim, realizations):
        # the method doing the real stuff; use compute instead
        if seed is not None:
            numpy.random.seed(seed)
        result = collections.OrderedDict()
        sctx, rctx, dctx = self.ctx

        if self.truncation_level == 0:
            assert self.correlation_model is None
            for imti, imt in enumerate(self.imts):
                mean, _stddevs = gsim.get_mean_and_stddevs(
                    sctx, rctx, dctx, imt, stddev_types=[])
                mean = gsim.to_imt_unit_values(mean)
                mean.shape += (1, )
                mean = mean.repeat(realizations, axis=1)
                result[imti] = mean
            return result
        elif self.truncation_level is None:
            distribution = scipy.stats.norm()
        else:
            assert self.truncation_level > 0
            distribution = scipy.stats.truncnorm(
                - self.truncation_level, self.truncation_level)

        for imti, imt in enumerate(self.imts):
            if gsim.DEFINED_FOR_STANDARD_DEVIATION_TYPES == \
               set([StdDev.TOTAL]):
                # If the GSIM provides only total standard deviation, we need
                # to compute mean and total standard deviation at the sites
                # of interest.
                # In this case, we also assume no correlation model is used.
                if self.correlation_model:
                    raise CorrelationButNoInterIntraStdDevs(
                        self.correlation_model, gsim)

                mean, [stddev_total] = gsim.get_mean_and_stddevs(
                    sctx, rctx, dctx, imt, [StdDev.TOTAL])
                stddev_total = stddev_total.reshape(stddev_total.shape + (1, ))
                mean = mean.reshape(mean.shape + (1, ))

                total_residual = stddev_total * distribution.rvs(
                    size=(len(self.sites), realizations))
                gmf = gsim.to_imt_unit_values(mean + total_residual)
            else:
                mean, [stddev_inter, stddev_intra] = gsim.get_mean_and_stddevs(
                    sctx, rctx, dctx, imt,
                    [StdDev.INTER_EVENT, StdDev.INTRA_EVENT])
                stddev_intra = stddev_intra.reshape(stddev_intra.shape + (1, ))
                stddev_inter = stddev_inter.reshape(stddev_inter.shape + (1, ))
                mean = mean.reshape(mean.shape + (1, ))

                intra_residual = stddev_intra * distribution.rvs(
                    size=(len(self.sites), realizations))

                if self.correlation_model is not None:
                    ir = self.correlation_model.apply_correlation(
                        self.sites, imt, intra_residual)
                    # this fixes a mysterious bug: ir[row] is actually
                    # a matrix of shape (E, 1) and not a vector of size E
                    intra_residual = numpy.zeros(ir.shape)
                    for i, val in numpy.ndenumerate(ir):
                        intra_residual[i] = val

                inter_residual = stddev_inter * distribution.rvs(
                    size=realizations)

                gmf = gsim.to_imt_unit_values(
                    mean + intra_residual + inter_residual)

            result[imti] = gmf

        return result

    def compute(self, seed, eids, rlzs_by_gsim=None, min_iml=None):
        """
        Compute a ground motion array for the given sites.

        :param seed:
            seed for the numpy random number generator
        :param eids:
            event IDs, a list of integers
        :param rlzs_by_gsim:
            a dictionary {gsim instance: realizations}
        :param min_iml:
            an array minimum intensity per intensity measure type
        :returns:
            a numpy array of dtype gmv_dt
        """
        gmfa = []
        for sid, imti, rlz, gmvs_eids in self.calcgmfs(
                seed, eids, rlzs_by_gsim, min_iml):
            for gmv, eid in zip(*gmvs_eids):
                gmfa.append((sid, eid, rlz.ordinal, imti, gmv))
        return numpy.array(gmfa, gmv_dt)

    def calcgmfs(self, seed, eids, rlzs_by_gsim, min_iml=None):
        """
        Compute the ground motion fields for the given gsims, sites,
        multiplicity and seed.

        :param multiplicity:
            the number of GMFs to return
        :param seed:
            seed for the numpy random number generator
        :param rlzs_by_gsim:
            a dictionary {gsim instance: realizations}
        :yields:
            pairs (sid, imti, rlz, gmvs_eids)
        """
        multiplicity = len(eids)
        sids = self.sites.sids
        for i, gsim in enumerate(self.gsims):
            for rlzi, rlz in enumerate(rlzs_by_gsim[gsim]):
                for imti, gmf in self._compute(
                        seed + rlzi, gsim, multiplicity).items():
                    for sid, gmvs in zip(sids, gmf):
                        if min_iml is not None:  # is an array
                            ok = gmvs >= min_iml[imti]
                            gmvs_eids = (gmvs[ok], eids[ok])
                        else:
                            gmvs_eids = (gmvs, eids)
                        yield sid, imti, rlz, gmvs_eids


# this is not used in the engine; it is still useful for usage in IPython
# when demonstrating hazardlib capabilities
def ground_motion_fields(rupture, sites, imts, gsim, truncation_level,
                         realizations, correlation_model=None,
                         rupture_site_filter=filters.rupture_site_noop_filter,
                         seed=None):
    """
    Given an earthquake rupture, the ground motion field calculator computes
    ground shaking over a set of sites, by randomly sampling a ground shaking
    intensity model. A ground motion field represents a possible 'realization'
    of the ground shaking due to an earthquake rupture. If a non-trivial
    filtering function is passed, the final result is expanded and filled
    with zeros in the places corresponding to the filtered out sites.

    .. note::

     This calculator is using random numbers. In order to reproduce the
     same results numpy random numbers generator needs to be seeded, see
     http://docs.scipy.org/doc/numpy/reference/generated/numpy.random.seed.html

    :param openquake.hazardlib.source.rupture.Rupture rupture:
        Rupture to calculate ground motion fields radiated from.
    :param openquake.hazardlib.site.SiteCollection sites:
        Sites of interest to calculate GMFs.
    :param imts:
        List of intensity measure type objects (see
        :mod:`openquake.hazardlib.imt`).
    :param gsim:
        Ground-shaking intensity model, instance of subclass of either
        :class:`~openquake.hazardlib.gsim.base.GMPE` or
        :class:`~openquake.hazardlib.gsim.base.IPE`.
    :param truncation_level:
        Float, number of standard deviations for truncation of the intensity
        distribution, or ``None``.
    :param realizations:
        Integer number of GMF realizations to compute.
    :param correlation_model:
        Instance of correlation model object. See
        :mod:`openquake.hazardlib.correlation`. Can be ``None``, in which case
        non-correlated ground motion fields are calculated. Correlation model
        is not used if ``truncation_level`` is zero.
    :param rupture_site_filter:
        Optional rupture-site filter function. See
        :mod:`openquake.hazardlib.calc.filters`.
    :param int seed:
        The seed used in the numpy random number generator
    :returns:
        Dictionary mapping intensity measure type objects (same
        as in parameter ``imts``) to 2d numpy arrays of floats,
        representing different realizations of ground shaking intensity
        for all sites in the collection. First dimension represents
        sites and second one is for realizations.
    """
    ruptures_sites = list(rupture_site_filter([(rupture, sites)]))
    if not ruptures_sites:
        return dict((imt, numpy.zeros((len(sites), realizations)))
                    for imt in imts)
    [(rupture, sites)] = ruptures_sites
    gc = GmfComputer(rupture, sites, [str(imt) for imt in imts], [gsim],
                     truncation_level, correlation_model)
    result = gc._compute(seed, gsim, realizations)
    for imti, gmf in result.items():
        # makes sure the lenght of the arrays in output is the same as sites
        if rupture_site_filter is not filters.rupture_site_noop_filter:
            result[imti] = sites.expand(gmf, placeholder=0)

    return {gc.imts[imti]: result[imti] for imti in result}
