# -*- encoding: utf-8 -*-
import os
import unittest
import tempfile
from openquake.nrmllib import InvalidFile
from openquake.nrmllib.csvmanager import ZipArchive, DirArchive, MemArchive, \
    CSVManager

DATADIR = os.path.join(os.path.dirname(__file__), 'data')

DVSet = '''\
vulnerabilitySetID,assetCategory,lossCategory,IMT
PAGER,population,fatalities,MMI
NPAGER,population,fatalities,MMI
'''

DVFun = '''\
vulnerabilitySetID,vulnerabilityFunctionID,probabilisticDistribution
PAGER,IR,LN
PAGER,PK,LN
NPAGER,AA,LN
NPAGER,BB,LN
'''


def fake_archive(dvs=DVSet, dvf=DVFun, dvd=''):
    return MemArchive([
        ('test__DiscreteVulnerabilitySet.csv', dvs),
        ('test__DiscreteVulnerability.csv', dvf),
        ('test__DiscreteVulnerabilityData.csv', dvd),
        ])


class ConvertGoodFilesTestCase(unittest.TestCase):
    """
    These are the tests for well formed files. They check that it is
    possible to start from a valid NRML file, convert into into a .zip
    archive of flat files and the convert back the archive to the
    original .xml file.
    """
    def check_round_trip(self, model_xml):
        # from nrml -> csv and back, all in memory
        name = model_xml[:-4]  # strips the .xml extension
        fname = os.path.join(DATADIR, model_xml)
        archive = MemArchive([])
        manager = CSVManager(name, archive)
        manager.convert_from_nrml(fname)
        outname = os.path.join(tempfile.gettempdir(), model_xml)
        with open(outname, 'w') as out:
            manager.convert_to_nrml(out)
        if open(fname).read() != open(outname).read():
            raise ValueError('Files %s and %s are different' %
                             (fname, outname))

    def test_vulnerability(self):
        self.check_round_trip('vulnerability-model-discrete.xml')

    def test_fragility_discrete(self):
        self.check_round_trip('fragility-model-discrete.xml')

    def test_fragility_continuous(self):
        self.check_round_trip('fragility-model-continuous.xml')

    def test_exposure_population(self):
        self.check_round_trip('exposure-population.xml')

    ## TEMPORARILY COMMENTED OUT TEST

    #def test_exposure_buildings(self):
    #    self.check_round_trip('exposure-buildings.xml')

    def test_gmf_scenario(self):
        self.check_round_trip('gmf-scenario.xml')

    def test_gmf_event_based(self):
        self.check_round_trip('gmf-event-based.xml')


class ConvertBadFilesTestCase(unittest.TestCase):

    def test_empty_archive(self):
        empty_archive = MemArchive([])
        with self.assertRaises(RuntimeError):
            CSVManager('test', empty_archive).convert_to_node()

    def test_empty_files(self):
        archive = fake_archive('', '', '')
        node = CSVManager('test', archive).convert_to_node()
        self.assertEqual(node.to_str(), 'vulnerabilityModel\n')

    def test_no_header(self):
        archive = fake_archive(dvd='5.00,0.00,0.30')
        man = CSVManager('test', archive)
        with self.assertRaises(InvalidFile):
            man.convert_to_node().to_str()

    def test_no_data(self):
        archive = fake_archive(
            dvd='vulnerabilitySetID,vulnerabilityFunctionID,'
            'IML,lossRatio,coefficientsVariation')
        man = CSVManager('test', archive)
        with self.assertRaises(InvalidFile):
            man.convert_to_node()

    def test_bad_data_1(self):
        archive = fake_archive(dvd='''\
vulnerabilitySetID,vulnerabilityFunctionID,IML,lossRatio,coefficientsVariation
PAGER,IR,5.00,0.00,0.30
PAGER,IR,5.50,0.00,0.30
PAGER,IR,6.00,0.00,''')
        man = CSVManager('test', archive)
        with self.assertRaises(InvalidFile):
            man.convert_to_node()

    def test_bad_data_2(self):
        archive = fake_archive(dvd='''\
vulnerabilitySetID,vulnerabilityFunctionID,IML,lossRatio,coefficientsVariation
PAGER,IR,5.00,0.00,0.30
PAGER,IR,5.50,0.00,0.30
PAGER,IR,6.00,0.00''')
        man = CSVManager('test', archive)
        with self.assertRaises(InvalidFile):
            man.convert_to_node()
