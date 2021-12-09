#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2018 GENESYS Lab..
#
# This is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this software; see the file COPYING.  If not, write to
# the Free Software Foundation, Inc., 51 Franklin Street,
# Boston, MA 02110-1301, USA.
#


import struct
import pmt
import numpy, os
import sys
import math
import cmath
from gnuradio import gr
import json
import logging


# UDP related libraries
import socket
import struct
import threading
import time


class CSI_feedback_adapter_py(gr.basic_block):
    """
    docstring for block CSI_feedback_adapter_py

    """

    file_path = ""
    numTxAntennas = 1
    beamweight = complex(1.0, 1.0)
    delay = 0


    # Static parameter used during binary file read operation
    binary_byte_read = 8

    ## Constructor of CSI_feedback_adapter_py class
    #  @param source_type 0: File source, 1: UDP socket
    #  @param file_path
    #  TBD ...
    #  @TODO <optional> Move UDP class to a different file
    def __init__(self,
                 source_type,
                 file_path,
                 number_of_tx_antennas,
                 multicast_IP,
                 multicast_port,
                 Tx_ID):

        gr.basic_block.__init__(self,
            name="CSI_feedback_adapter_py",
            in_sig=None,
            out_sig=None)

        print "Source : {}".format(source_type)
        print "Transmitter ID: {}".format(Tx_ID)


        ### Store and initialize generic object parameters
        self.numTxAntennas = number_of_tx_antennas
        self.file_path = file_path
        self.Tx_ID = int (Tx_ID)

        logging.basicConfig(format= '%(asctime)s.%(msecs)03d %(levelname)s %(message)s', datefmt= '%s', filename='/tmp/csi_tx.log', filemode= 'w', level=logging.DEBUG)
        self.csi_logger = logging.getLogger()
        self.debug = False
        # Init input and output ports
        self.message_port_register_in(pmt.intern("trigger"))
        self.message_port_register_out(pmt.intern("beamweight"))

        self.message_port_register_out(pmt.intern("delay"))

        if source_type == 0:
            """ Bind file read to input message port """
            self.set_msg_handler(pmt.intern("trigger"), self.read_and_send_beamweight)

        elif source_type == 1:
            """ Generate a thread waiting for incoming datagrams"""

            ## @todo only triggers bw not delay, it should be included if neccessary.
            # Bind optional message handler to forward pre-stored bw
            self.set_msg_handler(pmt.intern("trigger"), self.send_beamweight)

            address = multicast_IP, int(multicast_port)
            self.UDP_socket = UDPServer(address, self.udp_packet_handler)
            self.UDP_socket.start()

        else:
            print "Undefined source type while initializing CSI-fb-adapter."
            raise ValueError("Undefined source type while initializing CSI-fb-adapter.")

    def send_beamweight(self, msg):
        weight = pmt.from_complex(self.beamweight)
        self.message_port_pub(pmt.intern("beamweight"), weight)
        #print "BW sent: {}".format(weight)


    def send_delay(self, msg):
        #delay = pmt.from_string(self.beamweight)
	#delay = pmt.from_double(self.beamweight)
	delay = pmt.string_to_symbol(str(self.delay))
	#print type(delay)
        self.message_port_pub(pmt.intern("delay"), delay)
        print "Delay sent: {}".format(delay)

    def read_and_send_beamweight(self, msg):
        bw_from_file = self.read_bw_from_file()

        if bw_from_file is None:
            print "Failed to get beamweight from the source."
        else:
            # Update the bw
            self.beamweight = bw_from_file

        self.send_beamweight(None)


    def udp_packet_handler(self, json_package):
        #print(json_package)
        de_serialized = json.loads(json_package)
        length = len(de_serialized)

        update_in_delay = False
        try:
            ## @TODO Following if/else statement should be revised.
            """ if self.Tx_ID == 1 and de_serialized[0]['Tx_ID'] == 1:
                print 'For TX 1'
                real = de_serialized[0]['real']
                imaginary = de_serialized[0]['imaginary']
            elif self.Tx_ID == 2 and de_serialized[1]['Tx_ID'] == 2:
                print 'For TX 2'
                real = de_serialized[1]['real']
                imaginary = de_serialized[1]['imaginary']
            elif self.Tx_ID == 3 and de_serialized[2]['Tx_ID'] == 3:
                print 'For TX 3'
                real = de_serialized[2]['real']
                imaginary = de_serialized[2]['imaginary']
            elif self.Tx_ID == 4 and de_serialized[3]['Tx_ID'] == 4:
                print 'For TX 4'
                real = de_serialized[3]['real']
                imaginary = de_serialized[3]['imaginary']  """

            target_object = de_serialized[self.Tx_ID-1]

            if int (target_object['Tx_ID']) != self.Tx_ID:
                raise Exception("Inconsistent Tx array from RX")
            else:
                #print 'For TX {}'.format(self.Tx_ID)
                real = target_object['real']
                imaginary = target_object['imaginary']

                ## Filter out the echos
                if int (target_object['delay']) > 0 and \
                        int (target_object['delay']) != self.delay:
                    update_in_delay = True
                    self.delay = int(target_object['delay'])


        except IndexError:
            print "Transmitter number is out of index. - Tx: {}".format(self.Tx_ID)
        except KeyError as format_error:
            print "Keys are not defined in the received packet:\n{}".format(format_error)
        except Exception as e:
            print e

        # Reconstructing channel estimation value in complex format
        # self.channel_est = [real, imaginary]
        channel_est_complex = complex(real, imaginary)
        #print channel_est_complex
        self.csi_logger.info('{},{}'.format(int(time.time()*1000000),channel_est_complex))
        abs_channel_est_antennas = abs(channel_est_complex)
        phase_correction = channel_est_complex / abs_channel_est_antennas

        beamweight = 1/phase_correction
        self.beamweight = beamweight

        self.send_beamweight(None)

        if update_in_delay:
            self.send_delay(None)


    def read_bw_from_file(self):

        # Extracting the real and imaginary values of channel estimation
        # First 8 bytes of binary file 'weights_tx2.bin' contain real values
        # Second 8 bytes of binary file 'weights_tx2.bin' contain imaginary values
        # Third 8 bytes of binary file 'weights_tx2.bin' contain the time correction value.
        file_path_real = self.file_path + "chEst_real.bin"
        file_path_imag = self.file_path + "chEst_imag.bin"

        try:
            real_file = open(file_path_real)
            real_data = real_file.read()
            imag_file = open(file_path_imag)
            imag_data = imag_file.read()

        except IOError:
            print "Could not read files in path: {}".format(self.file_path)


        try:
            """ @TODO Following if/else statement should be revised. """
            if self.Tx_ID == 1:
                real = struct.unpack('d', real_data[0:self.binary_byte_read])[0]
                imaginary = struct.unpack('d', imag_data[0:self.binary_byte_read])[0]

            elif self.Tx_ID == 2:
                real = struct.unpack('d', real_data[self.binary_byte_read:2*self.binary_byte_read])[0]
                imaginary = struct.unpack('d', imag_data[self.binary_byte_read:2*self.binary_byte_read])[0]

            elif self.Tx_ID == 3:
                real = struct.unpack('d', real_data[2*self.binary_byte_read:3*self.binary_byte_read])[0]
                imaginary = struct.unpack('d', imag_data[2*self.binary_byte_read:3*self.binary_byte_read])[0]

            elif self.Tx_ID == 4:
                real = struct.unpack('d', real_data[3*self.binary_byte_read:4*self.binary_byte_read])[0]
                imaginary = struct.unpack('d', imag_data[3*self.binary_byte_read:4*self.binary_byte_read])[0]

            else:
                print "Unexpected transmitter number."
                #raise Exception("Unexpected transmitter number. ")

        except UnboundLocalError:
                print "Could not generate parameter from the files in path: {}".format(self.file_path)
        except IndexError:
                print "Index error on parsed binary file."

        else:
            # Reconstructing channel estimation value in complex format
            channel_est_complex = complex(real, imaginary)

            # print channel_est_complex

            abs_channel_est_antennas = abs(channel_est_complex)
            phase_correction = channel_est_complex / abs_channel_est_antennas

            beamweight = 1/phase_correction

            return beamweight





    def forecast(self, noutput_items, ninput_items_required):
        raise Exception("@CSI_feedback_adapter_py:forecast - This function should not be called")


    def general_work(self, input_items, output_items):
        raise Exception("@CSI_feedback_adapter_py:general_work - This function should not be called")


class UDPServer(threading.Thread):
    def __init__(self, address, udp_packet_handler):
        print("UDP server generated.")

        self.multicast_group = address[0]
        self.port = address[1]

        self.udp_packet_handler = udp_packet_handler

        threading.Thread.__init__(self)

    def run(self):
        try:
            # Create the socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # Bind to the server address
            sock.bind(('', self.port))

            # Tell the operating system to add the socket to the multicast group
            # on all interfaces.
            group = socket.inet_aton(self.multicast_group)
            mreq = struct.pack('4sL', group, socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        except socket.error as exp:
            print("Exception while creating the socket\n%s" % exp)
            sock.close()


        # Receive loop
        while True:
            # print >> sys.stderr, '\nwaiting to receive message'
            try:
                data, address = sock.recvfrom(1024)
            except socket.timeout:
                print('timed out, no incoming CSI feedback')
                break
            else:
                #print('received "%s" from %s - time: %f ' % (data, address, time.time() ) )
                self.udp_packet_handler(data)
