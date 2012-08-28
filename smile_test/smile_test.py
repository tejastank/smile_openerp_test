# -*- encoding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2011 Smile (<http://www.smile.fr>). All Rights Reserved
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

"""
Requirements: coverage
"""

import time
import os.path
import inspect
import traceback
import xml.etree.ElementTree as ElementTree

from osv import osv
import pooler
import tools
import addons
from release import major_version


class SmileTest(osv.osv_memory):
    _name = 'smile.test'

    def get_all_installed_module_list(self, cr, states):
        cr.execute("SELECT name from ir_module_module WHERE state IN %s", (tuple(states),))
        return [name for (name,) in cr.fetchall()]

    def build_test_list_from_modules(self, module_list):
        assert isinstance(module_list, list), 'Module list should be a list'
        module_test_files = {}
        for module_name in module_list:
            if major_version == '6.1':
                from modules.module import load_information_from_description_file
                info = load_information_from_description_file(module_name)
            else:
                info = addons.load_information_from_description_file(module_name)
            module_test_files[module_name] = info.get('test', [])
        return module_test_files

    def _run_test(self, cr, module_name, filename):
        _, ext = os.path.splitext(filename)
        pathname = os.path.join(module_name, filename)
        open_file = tools.file_open(pathname)
        if ext == '.sql':
            queries = open_file.read().split(';')
            for query in queries:
                new_query = ' '.join(query.split())
                if new_query:
                    cr.execute(new_query)
        elif ext == '.csv':
            tools.convert_csv_import(cr, module_name, pathname, open_file.read(), idref=None, mode='update', noupdate=False)
        elif ext == '.yml':
            tools.convert_yaml_import(cr, module_name, open_file, idref=None, mode='update', noupdate=False)
        else:
            tools.convert_xml_import(cr, module_name, open_file, idref=None, mode='update', noupdate=False)

    def test_suite_to_xunit(self, test_suite):
        xml_testsuite = ElementTree.Element('testsuite')
        for attr in test_suite:
            if attr != 'test_cases':
                xml_testsuite.attrib[attr] = unicode(test_suite[attr])
        for test_case in test_suite['test_cases']:
            xml_testcase = ElementTree.SubElement(xml_testsuite, 'testcase')
            for attr in test_case:
                if attr != 'error':
                    xml_testcase.attrib[attr] = unicode(test_case[attr])
            if test_case['error']:
                error = ElementTree.SubElement(xml_testcase, 'error')
                error.text = test_case['error']['stack_trace']
                error.attrib['type'] = test_case['error']['type']
                error.attrib['message'] = test_case['error']['message']
        return ElementTree.tostring(xml_testsuite, encoding='utf8')

    def test(self, cr, uid, module_list='all', xunit=True, context=None):
        if module_list == 'all' or 'all' in module_list:
            module_list = self.get_all_installed_module_list(cr, ('installed', 'to upgrade'))
        module_test_files = self.build_test_list_from_modules(module_list)

        new_cr = pooler.get_db(cr.dbname).cursor()

        test_suite = {'name': 'smile.test',
                      'tests': 0,
                      'errors': 0,
                      'failures': 0,
                      'skip': 0,
                      'test_cases': [], }
        try:
            for module_name in module_test_files:
                for filename in module_test_files[module_name]:
                    test_case = {'classname': module_name,
                                 'name': filename,
                                 'time': 0,
                                 'error': {}, }
                    start = time.time()
                    try:
                        test_suite['tests'] += 1
                        self._run_test(new_cr, module_name, filename)

                    except Exception, e:
                        test_suite['errors'] += 1
                        traceback_msg = traceback.format_exc()
                        # Yaml traceback do not work, certainly because of the compile clause
                        # that messes up line numbers

                        possible_yaml_statement, statement_lineno = None, None
                        # Get the deepest frame
                        frame_list = inspect.trace()
                        deepest_frame = frame_list[-1][0]
                        locals_to_match = ['statements', 'code_context', 'model']
                        for frame_inf in frame_list:
                            frame = frame_inf[0]
                            if possible_yaml_statement and not statement_lineno:
                                # possible_yaml_statement was found in last frame
                                # and here is the expected lineno
                                statement_lineno = frame.f_lineno
                            for local_to_match in locals_to_match:
                                if local_to_match not in frame.f_locals:
                                    break
                            else:
                                # all locals found ! we are in process_python function
                                possible_yaml_statement = frame.f_locals['statements']

                        if possible_yaml_statement:
                            numbered_line_statement = ""
                            for index, line in enumerate(possible_yaml_statement.split('\n'), start=1):
                                numbered_line_statement += "%03d>  %s\n" % (index, line)
                            yaml_error = "For yaml file, check line %s of statement:\n%s" % (statement_lineno,
                                                                                             numbered_line_statement)

                            traceback_msg += '\n\n%s' % yaml_error

                        traceback_msg += """\n\nLocal variables in deepest are: %s """ % repr(deepest_frame.f_locals)
                        test_case['error'] = {'type': str(type(e)),
                                              'message': repr(e),
                                              'stack_trace': traceback_msg, }
                    finally:
                        test_case['time'] = (time.time() - start)
                        test_suite['test_cases'].append(test_case)
                new_cr.rollback()
        finally:
            new_cr.close()
        if xunit:
            return self.test_suite_to_xunit(test_suite)
        return test_suite

    def test_to_xunitfile(self, cr, uid, module_list, filename, context=None):
        with open(filename, 'w') as xunit_file:
            xunit_str = self.test(cr, uid, module_list, xunit=True, context=context)
            xunit_file.write(xunit_str)
        return True

SmileTest()
