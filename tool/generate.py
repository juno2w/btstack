#!/usr/bin/env python
# BlueKtichen GmbH (c) 2014

import glob
import re
import sys
import os

print '''
Java binding generator for BTstack
Copyright 2014, BlueKitchen GmbH
'''

# com.bluekitchen.btstack.BTstack.java templates
java_btstack_header = \
'''/** 
 * BTstack Client Library
 */

package %s;

public class BTstack extends BTstackClient {
    
'''
java_btstack_command = '''
    public boolean %s(%s){
        // %s
        int command_len = %s;
        byte[] command = new byte[command_len];
        Util.storeBt16(command, 0, Util.opcode(%s, %s));
        int offset = 2;
        Util.storeByte(command, offset, command_len - 3);
        offset++;
%s
        Packet packet = new Packet(Packet.HCI_COMMAND_PACKET, 0, command, command.length);
        return sendPacket(packet);
    }
'''
java_btstack_footer = '''
}
'''

# com.bluekitchen.btstack.EventFactory template
java_event_factory_template = \
'''package {0};

import {0}.event.*;

public class EventFactory {{

    /** @brief event codes */

{1}
    public static Event eventForPacket(Packet packet){{
        int eventType = Util.readByte(packet.getBuffer(), 0);
        switch (eventType){{
{2}        
        case 0x3e:  // LE_META_EVENT
            int subEventType = Util.readByte(packet.getBuffer(), 2);
            switch (subEventType){{
{3}            
            default:
                return new Event(packet);
            }}

        default:
            return new Event(packet);
        }}
    }}
}}
'''
java_event_factory_event = '''
        case {0}:
            return new {1}(packet);
'''
java_event_factory_subevent = '''
            case {0}:
                return new {1}(packet);
'''

# com.bluekitchen.btstack.events.* template
java_event_template = \
'''package {0}.event;

import {0}.*;

public class {1} extends Event {{

    public {1}(Packet packet) {{
        super(packet);
    }}
    {2}
    {3}
}}
'''

java_event_getter = \
'''
    /**
     * @return {1} as {0}
     */
    public {0} get{1}(){{
        {2}
    }}
'''

java_event_getter_data = \
'''int len = get{0}();
        byte[] result = new byte[len];
        System.arraycopy(data, {1}, result, 0, len);
        return result;'''

java_event_getter_remaining_data = \
'''int len = getPayloadLen() - {0};
        byte[] result = new byte[len];
        System.arraycopy(data, {0}, result, 0, len);
        return result;'''

java_event_to_string = \
'''
    public String toString(){{
        StringBuffer t = new StringBuffer();
        t.append("{0} < type = ");
        t.append(String.format("0x%02x, ", getEventType()));
        t.append(getEventType());
{1}        t.append(" >");
        return t.toString();
    }}
'''


# global variables/defines
package='com.bluekitchen.btstack'
gen_path = 'gen/' + package.replace('.', '/')
hci_cmds_h_path = '../../src/hci_cmds.h'
hci_cmds_c_path = '../../src/hci_cmds.c'
hci_h_path = '../../src/hci.h'

defines = dict()
defines_used = set()

def assert_dir(path):
    if not os.access(path, os.R_OK):
        os.makedirs(path)

def cap(x):
    if x.lower() == 'btstack':
        return 'BTstack'
    acronyms = ['GAP', 'GATT', 'HCI', 'L2CAP', 'LE', 'RFCOMM', 'SM', 'SDP', 'UUID16', 'UUID128']
    if x.upper() in acronyms:
        return x.upper()
    return x.capitalize()

def camel_case(name):
    return ''.join(map(cap, name.split('_')))

def camel_case_var(name):
    if name in ['uuid128', 'uuid16']:
        return name
    camel = camel_case(name)
    return camel[0].lower() + camel[1:]

def read_defines(infile):
    global defines
    with open (infile, 'rb') as fin:

        for line in fin:
            parts = re.match('#define\s+(\w+)\s+(\w*)',line)
            if parts and len(parts.groups()) == 2:
                (key, value) = parts.groups()
                defines[key] = value

def java_type_for_btstack_type(type):
    param_types = { '1' : 'int', '2' : 'int', '3' : 'int', '4' : 'long', 'H' : 'int', 'B' : 'BD_ADDR',
                    'D' : 'byte []', 'E' : 'byte [] ', 'N' : 'String' , 'P' : 'byte []', 'A' : 'byte []',
                    'R' : 'byte []', 'S' : 'byte []',
                    'J' : 'int', 'L' : 'int', 'V' : 'byte []', 'U' : 'BT_UUID',
                    'X' : 'GATTService', 'Y' : 'GATTCharacteristic', 'Z' : 'GATTCharacteristicDescriptor',
                    'T' : 'String'}
    return param_types[type]

def size_for_type(type):
    param_sizes = { '1' : 1, '2' : 2, '3' : 3, '4' : 4, 'H' : 2, 'B' : 6, 'D' : 8, 'E' : 240, 'N' : 248, 'P' : 16,
                    'A' : 31, 'S' : -1, 'V': -1, 'J' : 1, 'L' : 2, 'U' : 16, 'X' : 20, 'Y' : 24, 'Z' : 18, 'T':-1}
    return param_sizes[type]

def create_command_java(fout, name, ogf, ocf, format, params):
    global java_btstack_command

    ind = '        '
    param_store = {
     '1' : 'Util.storeByte(command, offset, %s);',
     'J' : 'Util.storeByte(command, offset, %s);',
     '2' : 'Util.storeBt16(command, offset, %s);',
     'H' : 'Util.storeBt16(command, offset, %s);',
     'L' : 'Util.storeBt16(command, offset, %s);',
     '3' : 'Util.storeBt24(command, offset, %s);',
     '4' : 'Util.storeBt32(command, offset, %s);',
     'D' : 'Util.storeBytes(command, offset, %s, 8);',
     'E' : 'Util.storeBytes(command, offset, %s, 240);',
     'P' : 'Util.storeBytes(command, offset, %s, 16);',
     'A' : 'Util.storeBytes(command, offset, %s, 31);',
     'S' : 'Util.storeBytes(command, offset, %s);', 
     'B' : 'Util.storeBytes(command, offset, %s.getBytes());',
     'U' : 'Util.storeBytes(command, offset, %s.getBytes());', 
     'X' : 'Util.storeBytes(command, offset, %s.getBytes());', 
     'Y' : 'Util.storeBytes(command, offset, %s.getBytes());', 
     'Z' : 'Util.storeBytes(command, offset, %s.getBytes());', 
     'N' : 'Util.storeString(command, offset, %s, 248);',
     }
    # method arguments 
    arg_counter = 1
    args = []
    for param_type, arg_name in zip(format, params):
        arg_type = java_type_for_btstack_type(param_type)
        arg_size = size_for_type(param_type)
        arg = (param_type, arg_type, arg_size, arg_name)
        args.append(arg)
        arg_counter += 1

    # method argument declaration 
    args2 = []
    for arg in args:
        args2.append('%s %s' % (arg[1], arg[3]))
    args_string = ', '.join(args2)

    # command size (opcode, len)
    size_fixed = 3
    size_var = ''
    for arg in args:
        size = arg[2]
        if size > 0:
            size_fixed += size
        else:
            size_var += ' + %s.length' % arg[3]
    size_string = '%u%s' % (size_fixed, size_var)

    store_params = ''

    length_name = ''
    for (param_type, arg_type, arg_size, arg_name) in args:
        if param_type in ['L', 'J']:
            length_name = arg_name
        if param_type == 'V':
            store_params += ind + 'Util.storeBytes(command, offset, %s, %s);' % (arg_name, length_name) + '\n';
            store_params += ind + 'offset += %s;\n' % length_name;
            length_name = ''
        else:
            store_params += ind + (param_store[param_type] % arg_name) + '\n';
            size = arg_size
            if size > 0:
                store_params += ind + 'offset += %u;\n' % arg_size;
            else:
                store_params += ind + 'offset += %s.length;\n' % arg_name

    fout.write( java_btstack_command % (name, args_string, format, size_string, ogf, ocf, store_params))

def mark_define_as_used(term):
    if term.startswith('0'):
        return
    defines_used.add(term)

def java_define_string(key):
    global defines
    return '    public static final int %s = %s;\n' % (key, defines[key])

def java_defines_string(keys):
    return '\n'.join( map(java_define_string, sorted(keys)))

def parse_commands(infile):

    global gen_path
    assert_dir(gen_path)
    
    outfile = '%s/BTstack.java' % gen_path

    with open(outfile, 'w') as fout:
    
        fout.write(java_btstack_header % package)

        with open (infile, 'rb') as fin:

            params = []
            for line in fin:

                parts = re.match('.*@param\s*(\w*)\s*', line)
                if parts and len(parts.groups()) == 1:
                    param = parts.groups()[0]
                    params.append(camel_case_var(param))
                    continue

                declaration = re.match('const\s+hci_cmd_t\s+(\w+)[\s=]+', line)
                if declaration:
                    command_name = camel_case(declaration.groups()[0])
                    if command_name.endswith('Cmd'):
                        command_name = command_name[:-len('Cmd')]
                    continue

                definition = re.match('\s*OPCODE\\(\s*(\w+)\s*,\s+(\w+)\s*\\)\s*,\s\\"(\w*)\\".*', line)
                if definition:
                    (ogf, ocf, format) = definition.groups()
                    if len(params) != len(format):
                        params = []
                        arg_counter = 1
                        for f in format:
                            arg_name = 'arg%u' % arg_counter
                            params.append(arg_name)
                            arg_counter += 1
                    create_command_java(fout, command_name, ogf, ocf, format, params);
                    mark_define_as_used(ogf)
                    mark_define_as_used(ocf)
                    params = []
                    continue

        fout.write('\n    /** defines used */\n\n')
        for key in sorted(defines_used):
            fout.write(java_define_string(key))

        fout.write(java_btstack_footer)

def create_event(event_name, format, args):
    global gen_path
    global package
    global java_event_template

    param_read = {
     '1' : 'return Util.readByte(data, %u);',
     'J' : 'return Util.readByte(data, %u);',
     '2' : 'return Util.readBt16(data, %u);',
     '3' : 'return Util.readBt24(data, %u);',
     '4' : 'return Util.readBt32(data, %u);',
     'H' : 'return Util.readBt16(data, %u);',
     'L' : 'return Util.readByte(data, %u);',
     'B' : 'return Util.readBdAddr(data, %u);',
     'X' : 'return Util.readGattService(data, %u);',
     'Y' : 'return Util.readGattCharacteristic(data, %u);',
     'Z' : 'return Util.readGattCharacteristicDescriptor(data, %u);',
     'T' : 'int offset = %u; \n        return Util.getText(data, offset, getPayloadLen()-offset);',
     'N' : 'return Util.getText(data, %u, 248);',
     # 'D' : 'Util.storeBytes(data, %u, 8);',
     # 'E' : 'Util.storeBytes(data, %u, 240);',
     # 'P' : 'Util.storeBytes(data, %u, 16);',
     # 'A' : 'Util.storeBytes(data, %u, 31);',
     # 'S' : 'Util.storeBytes(data, %u);'
     }

    gen_event_path = '%s/event' % gen_path
    outfile = '%s/%s.java' % (gen_event_path, event_name)
    with open(outfile, 'w') as fout:
        offset = 2
        getters = ''
        length_name = ''
        for f, arg in zip(format, args):
            # just remember name
            if f in ['L','J']:
                length_name = camel_case(arg)
            if f == 'R':    
                # remaining data
                access = java_event_getter_remaining_data.format(offset)
                size = 0
            elif f == 'V':
                access = java_event_getter_data.format(length_name, offset)
                size = 0
            else: 
                access = param_read[f] % offset
                size = size_for_type(f)
            getters += java_event_getter.format(java_type_for_btstack_type(f), camel_case(arg), access)
            offset += size
        to_string_args = ''
        for arg in args:
            to_string_args += '        t.append(", %s = ");\n' % arg
            to_string_args += '        t.append(get%s());\n' % camel_case(arg)
        to_string_method = java_event_to_string.format(event_name, to_string_args)
        fout.write(java_event_template.format(package, event_name, getters, to_string_method))

def create_events(events):
    global gen_path
    gen_path_events = gen_path + '/event'
    assert_dir(gen_path_events)

    for event_type, event_name, format, args in events:
        event_name = camel_case(event_name)
        create_event(event_name, format, args)

def create_event_factory(events, le_events, defines):
    global gen_path
    global package
    global java_event_factory_event
    global java_event_factory_template

    outfile = '%s/EventFactory.java' % gen_path

    cases = ''
    for event_type, event_name, format, args in events:
        event_name = camel_case(event_name)
        cases += java_event_factory_event.format(event_type, event_name)
    subcases = ''
    for event_type, event_name, format, args in le_events:
        event_name = camel_case(event_name)
        subcases += java_event_factory_subevent.format(event_type, event_name)

    with open(outfile, 'w') as fout:
        defines_text = java_defines_string(defines)
        fout.write(java_event_factory_template.format(package, defines_text, cases, subcases))

def parse_events(path):
    global gen_path
    events = []
    le_events = []
    params = []
    event_types = set()
    format = None
    with open (path, 'rb') as fin:
        for line in fin:
            parts = re.match('.*@format\s*(\w*)\s*', line)
            if parts and len(parts.groups()) == 1:
                format = parts.groups()[0]
            parts = re.match('.*@param\s*(\w*)\s*', line)
            if parts and len(parts.groups()) == 1:
                param = parts.groups()[0]
                params.append(param)
            parts = re.match('\s*#define\s+(\w+)\s+(\w*)',line)
            if parts and len(parts.groups()) == 2:
                (key, value) = parts.groups()
                if format != None:
                    if key.lower().startswith('hci_subevent_'):
                        le_events.append((value, key.lower().replace('hci_subevent_', 'hci_event_'), format, params))
                    else:
                        events.append((value, key, format, params))
                    event_types.add(key)
                params = []
                format = None
    return (events, le_events, event_types)

# # read defines from hci_cmds.h and hci.h
read_defines(hci_cmds_h_path)
read_defines(hci_h_path)

# # parse commands and generate BTstack.java
parse_commands(hci_cmds_c_path)

# parse hci.h to get used events
(events, le_events, event_types) = parse_events(hci_cmds_h_path)

# create events, le meta events, and event factory
create_events(events)
create_events(le_events)
create_event_factory(events, le_events, event_types)

# done
print 'Done!'
