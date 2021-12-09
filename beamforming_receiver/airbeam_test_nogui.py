#!/usr/bin/env python2
# -*- coding: utf-8 -*-
##################################################
# GNU Radio Python Flow Graph
# Title: Airbeam Test Nogui
# Generated: Thu Jan 21 01:18:44 2021
##################################################

from gnuradio import blocks
from gnuradio import eng_notation
from gnuradio import gr
from gnuradio import uhd
from gnuradio.eng_option import eng_option
from gnuradio.filter import firdes
from optparse import OptionParser
import beamforming
import time


class airbeam_test_nogui(gr.top_block):

    def __init__(self):
        gr.top_block.__init__(self, "Airbeam Test Nogui")

        ##################################################
        # Variables
        ##################################################
        self.trainingSignal_size = trainingSignal_size = 16456
        self.samp_rate = samp_rate = 400e3
        self.data_files_path = data_files_path = "/home/genesys/workarea-gnuradio/gnuradio/gr-beamforming/examples/data"

        ##################################################
        # Blocks
        ##################################################
        self.uhd_usrp_source_0 = uhd.usrp_source(
        	",".join(("serial=318D28D", "")),
        	uhd.stream_args(
        		cpu_format="fc32",
        		channels=range(1),
        	),
        )
        self.uhd_usrp_source_0.set_clock_source('external', 0)
        self.uhd_usrp_source_0.set_samp_rate(samp_rate)
        self.uhd_usrp_source_0.set_time_unknown_pps(uhd.time_spec())
        self.uhd_usrp_source_0.set_center_freq(uhd.tune_request(925e6,1e6), 0)
        self.uhd_usrp_source_0.set_gain(70, 0)
        self.uhd_usrp_source_0.set_antenna('RX2', 0)
        self.uhd_usrp_source_0.set_bandwidth(400e3, 0)
        self.uhd_usrp_source_0.set_auto_iq_balance(True, 0)
        self.blocks_file_sink_0_0 = blocks.file_sink(gr.sizeof_float*1, '/tmp/corr.dat', False)
        self.blocks_file_sink_0_0.set_unbuffered(False)
        self.blocks_file_sink_0 = blocks.file_sink(gr.sizeof_gr_complex*1, '/tmp/payload.dat', False)
        self.blocks_file_sink_0.set_unbuffered(False)
        self.blocks_complex_to_mag_0 = blocks.complex_to_mag(1)
        self.beamforming_filter_payload_py_0 = beamforming.filter_payload_py('payload')
        self.beamforming_correlate_and_tag_py_0 = beamforming.correlate_and_tag_py(trainingSignal_size, trainingSignal_size + 400 + 256* 64 + 100, 1, data_files_path + "/trainingSig", 1, 0)



        ##################################################
        # Connections
        ##################################################
        self.connect((self.beamforming_correlate_and_tag_py_0, 0), (self.beamforming_filter_payload_py_0, 0))
        self.connect((self.beamforming_correlate_and_tag_py_0, 1), (self.blocks_complex_to_mag_0, 0))
        self.connect((self.beamforming_filter_payload_py_0, 0), (self.blocks_file_sink_0, 0))
        self.connect((self.blocks_complex_to_mag_0, 0), (self.blocks_file_sink_0_0, 0))
        self.connect((self.uhd_usrp_source_0, 0), (self.beamforming_correlate_and_tag_py_0, 0))

    def get_trainingSignal_size(self):
        return self.trainingSignal_size

    def set_trainingSignal_size(self, trainingSignal_size):
        self.trainingSignal_size = trainingSignal_size

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.uhd_usrp_source_0.set_samp_rate(self.samp_rate)

    def get_data_files_path(self):
        return self.data_files_path

    def set_data_files_path(self, data_files_path):
        self.data_files_path = data_files_path


def main(top_block_cls=airbeam_test_nogui, options=None):

    try:    
        tb = top_block_cls()
        tb.start()
        raw_input('Press Enter to quit: ')
    except EOFError:
        pass
    except KeyboardInterrupt:
        tb.stop()
        tb.wait()
        import os
        print ('Start printing')
        dst_dir = '/home/genesys/KRI_csi_data/flight_pattern'
        src_file='/tmp/csi.log'
        dst_1 ='{}_{}.log'.format(os.path.basename(src_file).split('.log')[0],time.time())
        dst_file = os.path.join(dst_dir,dst_1)
        os.system('cp {} {}'.format(src_file,dst_file))
        src_2_file='/tmp/payload.dat'
        dst_2 = '{}_{}.dat'.format(os.path.basename(src_2_file).split('.dat')[0],time.time())
        dst_2_file = os.path.join(dst_dir, dst_2)
        os.system('cp {} {}'.format(src_2_file,dst_2_file))
        print ('File Saved')



if __name__ == '__main__':
    main()
