import base64
import shutil
from werkzeug.datastructures import FileStorage

import os
import json
import subprocess
import re
from tempfile import NamedTemporaryFile, mkdtemp

__author__ = 'Michel'


class PropCCompiler:

    def __init__(self):
        self.compiler_executable = "/opt/parallax/bin/propeller-elf-gcc"

        self.compile_actions = {
            "COMPILE": {"compile-options": [], "extension":".elf", "return-binary": False},
            "BIN": {"compile-options": [], "extension":".elf", "return-binary": True},
            "EEPROM": {"compile-options": [], "extension":".elf", "return-binary": True}
        }

        self.appdir = os.getcwd()

    def compile(self, action, source_files, app_filename):
        source_directory = mkdtemp()

        c_file_data = {}
        h_file_data = {}

        # Write all files to working directory
        # Header files
        for filename in source_files:
            if filename.endswith(".h"):
                with open(source_directory + "/" + filename, mode='w') as header_file:
                    if isinstance(source_files[filename], basestring):
                        file_content = source_files[filename]
                    elif isinstance(source_files[filename], FileStorage):
                        file_content = source_files[filename].stream.read()

                    header_file.write(file_content)

                # Check c file exists
                c_filename = filename[:-1] + 'c'
                if c_filename not in source_files:
                    return (False, None, '', 'Missing c file %s for header %s' % (c_filename, filename))

                h_file_data[filename] = {
                    'c_filename': c_filename
                }

        # C source files
        for filename in source_files:
            if filename.endswith(".c"):
                with open(source_directory + "/" + filename, mode='w') as source_file:
                    if isinstance(source_files[filename], basestring):
                        file_content = source_files[filename]
                    elif isinstance(source_files[filename], FileStorage):
                        file_content = source_files[filename].stream.read()

                    source_file.write(file_content)

                c_file_data[filename] = {
                    'includes': self.parse_includes(file_content)
                }

                # Check header file exists
                h_filename = filename[:-1] + 'h'
                c_file_data[filename]['library'] = h_filename in source_files

        compiler_output = ''
        library_order = []
        external_libraries = []


        # determine order and direct library dependencies
        for include in c_file_data[app_filename]['includes']:
            self.determine_order(include, library_order, external_libraries, h_file_data, c_file_data)

        # determine library dependencies
        external_libraries_info = {}
        for library in external_libraries:
            self.find_dependencies(library, external_libraries_info)

        if len(external_libraries) == 0:
            compiler_output += "Required libraries: None\n"
        else:
            compiler_output += "Required libraries: %s\n" % ', '.join(external_libraries)
        if len(library_order) == 0:
            compiler_output += "Library compile order: None needed\n"
        else:
            compiler_output += "Library compile order: %s\n" % ', '.join(library_order)

        # Precompile libraries
        for library in library_order:
            compiler_output += "Compiling: %s\n" % library
            pass

        # Compile binary

        shutil.rmtree(source_directory)

        return (False, None, compiler_output, '')

    def determine_order(self, header_file, library_order, external_libraries, header_files, c_files):
        if header_file not in library_order:
            if header_file + '.h' in header_files:
                includes = c_files[header_files[header_file + '.h']['c_filename']]['includes']
                for include in includes:
                    self.determine_order(include, library_order, external_libraries, header_files, c_files)
                library_order.append(header_file)
            else:
                if header_file not in external_libraries:
                    external_libraries.append(header_file)

    def find_dependencies(self, library, libraries):
        library_present = False
        for root, subFolders, files in os.walk(self.appdir + '/propeller-c-lib'):
            if library + '.h' in files:
                if library in root[root.rindex('/') + 1:]:
                    library_present = True
                    if library + '.c' in files:
                        with open(root + '/' + library + '.c') as library_code:
                            includes = self.parse_includes(library_code.read())
                    else:
                        with open(root + '/' + library + '.h') as header_code:
                            includes = self.parse_includes(header_code.read())

                    libraries[library] = {
                        'path': root
                    }

                    for include in includes:
                        if include not in libraries:
                            (success, logging) = self.find_dependencies(include, libraries)
                            if not success:
                                return (success, logging)
                else:
                    return (True, '')

        if library_present:
            return (True, '')
        else:
            return (False, 'Library %s not found' % library)

    def compile_lib(self, source_file, app_filename, libraries):
        pass

    def compile_binary(self, action, c_source_directory, source_file_code, app_filename, libraries):
        binary_file = NamedTemporaryFile(suffix=self.compile_actions[action]["extension"], delete=False)
        binary_file.close()

        for library in libraries:
            pass

        includes = self.parse_includes(source_file_code)  # parse includes
        descriptors = self.get_includes(includes)  # get lib descriptors for includes
        executing_data = self.create_executing_data(c_source_directory + "/" + app_filename, binary_file, descriptors)  # build execution command

        try:
            process = subprocess.Popen(executing_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # call compile

            out, err = process.communicate()

            if process.returncode == 0 and (err is None or len(err) == 0):
                out = "Compile successful\n"
                success = True
            else:
                success = False
        except OSError:
            out = ""
            err = "Compiler not found\n"
            success = False

        base64binary = ''

        if self.compile_actions[action]["return-binary"]:
            with open(binary_file.name) as bf:
                base64binary = base64.b32encode(bf.read())

        os.remove(binary_file.name)

        return (success, base64binary, out, err)

    def parse_includes(self, source_file):
        includes = set()

        for line in source_file.splitlines():
            if '#include' in line:
                match = re.match(r'^#include "(\w+).h"', line)
                if match:
                    includes.add(match.group(1))

        return includes

    def create_executing_data(self, main_c_file_name, binary_file, descriptors):
        executable = self.compiler_executable

        lib_directory = self.appdir + "/propeller-c-lib/"

        executing_data = [executable]
        for descriptor in descriptors:
            executing_data.append("-I")
            executing_data.append(lib_directory + descriptor["libdir"])
            executing_data.append("-L")
            executing_data.append(lib_directory + descriptor["memorymodel"]["cmm"])
        executing_data.append("-Os")
        executing_data.append("-mcmm")
        executing_data.append("-m32bit-doubles")
        executing_data.append("-std=c99")
        executing_data.append("-o")
        executing_data.append(binary_file.name)
        executing_data.append(main_c_file_name)
        executing_data.append("-lm")
        while len(descriptors) > 0:
            for descriptor in descriptors:
                executing_data.append("-l" + descriptor["name"])
            executing_data.append("-lm")
            del descriptors[-1]

        return executing_data
