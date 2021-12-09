#!/usr/bin/env python
# -*- coding: utf-8 -*-
# 
# Copyright 2019 Genesys lab..
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

import socket
import struct
import logging
import json
import numpy, os

try:
    from scipy import signal
except:
    print ("WARNING: Scipy module is not loaded. FFT-based cor. cannot be used.")
import pmt
from gnuradio import gr
import time

## Python libraries naming inconsistency
try:
    import queue
except:
    import Queue as queue


## https://wiki.gnuradio.org/index.php/Types_of_Blocks
#
# import gnuradio.extras
class correlate_and_tag_py(gr.sync_block):
    """
    docstring for block correlate_and_tag_py
    """
    def __init__(self, seq_len, frame_len, num_Tx, file_path, cor_method, feedback_type):
        gr.sync_block.__init__(self,
            name="correlate_and_tag_py",
            in_sig=[numpy.complex64],
            out_sig=[numpy.complex64, numpy.complex64])

        ## https://wiki.gnuradio.org/index.php/Types_of_Blocks
        #
        # self.set_auto_consume(False)

        self.gold_seq_length = seq_len
        self.frame_length = frame_len
        ## @todo this value should be dynamically assigned.
        self.payload_size = 256*64
        self.num_active_Tx = num_Tx

        """Logger init"""
        ##  @todo gr-logger is not working as expected, update in CMAKE files might be required.
        #
        self.log = gr.logger(str(__name__))
        self.log.set_level("INFO")
	
	#import ipdb;ipdb.set_trace()
	logging.basicConfig(format= '%(asctime)s.%(msecs)03d %(levelname)s %(message)s', datefmt= '%s', filename='/tmp/csi.log', filemode= 'w', level=logging.DEBUG)
	self.csi_logger = logging.getLogger()
        self.debug = False

        """Set UDP SERVER"""
        self.multicast_group = ('224.3.29.71', 10000)
        #self.server_address = ('', 10000)

        # Create the socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Bind to the server address
        # sock.bind(server_address)

        # Tell the operating system to add the socket to the multicast group
        # on all interfaces.
        try:

            group = socket.inet_aton('224.3.29.71')
            mreq = struct.pack('4sL', group, socket.INADDR_ANY)
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except Exception as e:
            logging.exception("Cannot init multicast UDP socket: {}".format(e))


        """Get Gold Sequences"""
        self.log.info("Receiver is initiated for {} active transmitters.".format(num_Tx))
        self.gold_sequences = numpy.empty((num_Tx, self.gold_seq_length),
                                          numpy.complex64)
        # print self.gold_sequences


        for tx_index in range(num_Tx):
            self.gold_sequences[tx_index,:] = numpy.array(self.get_training_signal(file_path, tx_index))


        """Internal Buffers"""
        self.buffer = [] #queue.Queue(maxsize=200000)
        self.output =  [] #queue.Queue(maxsize=200000)
        self.corr_output = [] #queue.Queue(maxsize=200000)

        """Internal States"""
        self.delay = True
        self.transmit = False

        self.correlation_window = []

        """Init fft method"""
        # Use fft based correlation
        if cor_method == 1:
            self.log.info("FFT-based correlation init.")
            self.correlate = self.signal_fft_correllation
        elif cor_method == 0 : # Default correlation function
            self.log.info("Default correlation init.")
            self.correlate = self.numpy_correlation
        else:
            self.log.error("Undefined correlation type.")
            self.correlate = None

        """ Init feedback type"""
        if feedback_type == 0: # Send only channel information
            self.log.info("Default feedback type init.")
            self.generate_feedback = self.default_csi_feedback
        elif  feedback_type == 1:
            self.log.info("Water filling algorithm feedback init.")
            self.generate_feedback = self.calculate_waterfilling_beamweights
        else:
            self.log.error("Undefined feedback type.")
            self.generate_feedback = None



    def work(self, input_items, output_items):
        self.debug = False

        in0 = input_items[0]
        out = output_items[0]
        corr_out = output_items[1]
        # <+signal processing here+>

        ## Reverse engineering - examining input and output buffers
        # print type(in0)
        # print str(in0.shape)
        # print str(in0.dtype)
        # print str(in0.flags)

        if self.debug:
            print( "Size of input: {} \t output: {}-{} buffers".format(len(in0), len(out), len(corr_out)))

        """ Fill the internal buffer with incoming items """
        """for indx, sample in enumerate(input_items[0]):
            self.buffer.put(sample)
        """
        self.buffer.extend(in0[:])

        if self.debug:
            print( "Size of internal buffer: {}".format(len(self.buffer)))

        # print "Size of output buffer: {}".format(len(out))

        """ Buffer has enough samples to run XCOR"""
        # buffer : internal buffer
        # correlation_window : items might be left after previous correlation
        # gold_seq_length
        # frame_length
        if len(self.buffer) + len(self.correlation_window) > self.gold_seq_length + self.frame_length:
            output_head = self.nitems_written(0)
            corr_output_head = self.nitems_written(1)

            initial_size = len(self.correlation_window)
            # Add items (samples) to correlation window
            #   to make its size equals gold_seq_length+frame_length

            item_size_to_add =  self.gold_seq_length + self.frame_length - initial_size
            self.correlation_window.extend(self.buffer[:item_size_to_add])
            self.buffer = self.buffer[item_size_to_add:]

            """while read_index < self.gold_seq_length + self.frame_length - initial_size:
                self.correlation_window.append(self.buffer.get())
                read_index = read_index + 1
            """
            """
            if self.debug:      
                print(     "Remaining inputs in buffer: {} \n" \
                                     "Number of samples in Cor. window: {}\n"
                                .format(
                                        self.buffer.qsize(),
                                        len(self.correlation_window)
                                        )
                            )
            """



            ## Variables which construct feedback
            channel_estimations = numpy.ones(self.num_active_Tx, dtype=numpy.complex64)
            delays = numpy.zeros(self.num_active_Tx, dtype=numpy.int)
            corr_indices = numpy.zeros(self.num_active_Tx, dtype=numpy.int)
            found_flags = numpy.zeros(self.num_active_Tx, dtype=numpy.int)

            # index to push samples to output buffer,
            # not related with the feedback
            push_index = 0

            ## a loop implemented for all active transmitters
            # run cross correlation to detect peaks and
            # calculate CSI
            for tx_index in range(self.num_active_Tx):
                self.debug = False

                if self.debug:	print(tx_index)
                s_time = time.time()
                x_cor_result = self.correlate(self.correlation_window, self.gold_sequences[tx_index])
                e_time = time.time()

                self.log.info("Xcorr calculation time: {} seconds".format(e_time - s_time))
                # print ("Xcorr calculation time: {} seconds".format(e_time - s_time))
                if self.debug:
                    print( "XCOR output type: {} \t size: {}".format(
                                        type(x_cor_result),
                                        len(x_cor_result)))


                ## MATLAB CODE
                # peakIntervals1 = find(abs(crossCorr{1})>(0.8*max(abs(crossCorr{1}))));

                tag_index = numpy.argmax(numpy.absolute(x_cor_result))
                peak_indices = self.get_peaks(x_cor_result)

                print("Tx: {} - Max item index: {}, First Peak index: {}".format(tx_index+1, tag_index, peak_indices[0] ))
		
		#self.csi_logger.info([tx_index+1, tag_index, peak_indices[0]])

                if peak_indices[0] > push_index:
                    push_index = peak_indices[0]

                # Calculate CSI
                s_index_of_gold_seq = peak_indices[0] - self.gold_seq_length/2
                e_index_of_gold_seq = s_index_of_gold_seq +  self.gold_seq_length

#                if s_index_of_gold_seq >= 0 and e_index_of_gold_seq <= len(self.correlation_window):
                if  e_index_of_gold_seq <= len(self.correlation_window):
                    corr_indices[tx_index] = s_index_of_gold_seq
                    found_flags[tx_index] = 1
                    print ("Training Signal starts :{} ends {}".format(s_index_of_gold_seq, e_index_of_gold_seq ))
                    """
                    print  numpy.divide(
                            self.correlation_window[s_index_of_gold_seq:e_index_of_gold_seq],
                            self.gold_sequences[tx_index], out=numpy.zeros_like(self.correlation_window[s_index_of_gold_seq:e_index_of_gold_seq]), where=self.gold_sequences[tx_index]!=0
                        )
                    print numpy.mean(   numpy.divide(
                        self.correlation_window[s_index_of_gold_seq:e_index_of_gold_seq],
                        self.gold_sequences[tx_index], out=numpy.zeros_like(self.correlation_window[s_index_of_gold_seq:e_index_of_gold_seq]), where=self.gold_sequences[tx_index]!=0
                    )           )
                    """

                    self.debug = False

                    ## Channel states
                    # @todo assign value to channel_estimations[tx_index]
                    # @todo if it is zero make it one\
                    if s_index_of_gold_seq < 0: 
		    	s_index_of_gold_seq = 0
		    	#print "start index of gold seq", s_index_of_gold_seq
		    	#print "end index of gold seq", e_index_of_gold_seq
			rec_gs = numpy.array(self.correlation_window[s_index_of_gold_seq:e_index_of_gold_seq])
		    	stored_gs = numpy.array((self.gold_sequences[tx_index])[s_index_of_gold_seq:e_index_of_gold_seq]) 
		    	#print "rec_gs", len(rec_gs)
		    	#print "stored_gs", len(stored_gs)
		    else:
		    	#print "start index of gold seq", s_index_of_gold_seq
		    	#print "end index of gold seq", e_index_of_gold_seq
                    	rec_gs = numpy.array(self.correlation_window[s_index_of_gold_seq:e_index_of_gold_seq])
		    	stored_gs = numpy.array(self.gold_sequences[tx_index])
		    	#print "rec_gs", len(rec_gs)
		    	#print "stored_gs", len(stored_gs)
                    """
                    channel_estimations[tx_index] = numpy.nanmean(   numpy.divide(
                        self.correlation_window[s_index_of_gold_seq:e_index_of_gold_seq],
                        self.gold_sequences[tx_index][s_index_of_gold_seq:e_index_of_gold_seq], out=numpy.zeros_like(self.correlation_window[s_index_of_gold_seq:e_index_of_gold_seq]), where=self.gold_sequences[tx_index][s_index_of_gold_seq:e_index_of_gold_seq]!=0
                    )           )
                    """
                    channel_estimations[tx_index] = numpy.nanmean(numpy.divide(rec_gs, stored_gs, out=numpy.zeros_like(rec_gs), where=stored_gs!=0))
		    
                    if self.debug: print("Tx: {} CSI: {}".format(tx_index+1, channel_estimations[tx_index] ))

                else:
                    self.debug = False
                    found_flags[tx_index] = 0
                    if self.debug: print("Could not correlate training signal {}".format(tx_index+1))

                # Create the TAGS
                key_flow = pmt.intern("training_Sig_{}".format(tx_index+1))
                value_flow = pmt.intern(str(self.gold_seq_length))
                # srcid = pmt.intern("sourceID")

                key_xcor = pmt.intern("training_Sig_{}".format(tx_index+1))
                value_xcor  = pmt.intern(str(peak_indices[0]))

                # attach TAGS to the output streams
                self.add_item_tag(0,
                                  output_head
                                  + len(self.output) # Items waiting in output queue
                                  + peak_indices[0]
                                  - self.gold_seq_length/2
                                  , key_flow, value_flow)

                self.add_item_tag(1, corr_output_head
                                  + len(self.corr_output) # Items waiting in output queue
                                  + peak_indices[0]
                                  , key_xcor, value_xcor)


                ## @note always mark payload based on the 1st Tx
                if tx_index == 0 :
                    key_payload = pmt.intern("payload")
                    value_payload = pmt.intern(str(self.payload_size))
                    self.add_item_tag(0,
                                      output_head
                                      + len(self.output) # Items waiting in output queue
                                      + peak_indices[0]
                                      + self.gold_seq_length/2
                                      + 400 # zero padding comes after Gold Seq.
                                      , key_payload, value_payload)


            max_index = int(numpy.max(corr_indices))

            # Calculate the individual delay values
            for tx_index in range(self.num_active_Tx):
                if int(found_flags[tx_index]) == 1:
                    possible_delay = max_index - int(corr_indices[tx_index])
                    if possible_delay < 500:
                        delays[tx_index] = possible_delay
                    else:
                        delays[tx_index] = 0
                if self.debug: print("Tx: {} Delay: {}".format(tx_index+1,  delays[tx_index]))
                #delays[tx_index] = 0

            ## Calculate beamweight based on feedback methods
            # Default: Simply return estimations
            # Waterfilling: Return weight calculated by WF alg.
            feedback_weights = self.generate_feedback(channel_estimations)

            dict_objects = []
            ## Fill out dictionary used in feedback
            for tx_index in range(self.num_active_Tx):
                dict_objects.append(
                    {
                        "Tx_ID": tx_index+1,
                        "real": float(numpy.real(feedback_weights[tx_index])),
                        "imaginary": float(numpy.imag(feedback_weights[tx_index])),
                        "delay": delays[tx_index]
                    }
                )

            self.debug = True
            if self.debug: print("JSON: {}".format(str(dict_objects)))
            serialized = json.dumps(dict_objects, indent=4)
            self.sock.sendto(serialized, self.multicast_group)

            self.debug = False

            # Push one frame
            push_size = push_index + self.frame_length - self.gold_seq_length/2

            if self.debug: print( "Sample size pushed to output buffers: {}".format(push_size))

            self.output.extend(self.correlation_window[:push_size])
            self.corr_output.extend(x_cor_result[:push_size])

            """
            self.push_data(self.correlation_window[:push_size], "output")
            self.push_data(x_cor_result[:push_size], "correlation_output")
            """
            self.correlation_window = self.correlation_window[push_size:]


        ## Forward the input as is
        # @todo delay and tag
        # corr_out[:] = numpy.ndarray(shape=(len(corr_out),),
        #                            dtype=numpy.complex64)[:len(corr_out)]
        if len (self.output) > len(out):
            out[:] = self.output[:len(out)]
            self.output = self.output[len(out):]
            # self.pull_data(len(out), "output")

        if len(self.corr_output) > len(corr_out):
            corr_out[:] = self.corr_output[:len(out)]
            self.corr_output = self.corr_output[len(out):]
            # self.pull_data(len(corr_out), "correlation_output")

        if self.debug:
            print( "Sizes of buffers\nout: {}, c_out: {}, in: {}".
                            format(len(out), len(corr_out), len(in0)))
        return len(in0)



    ## MATLAB CODE
    # peakIntervals1 = find(abs(crossCorr{1})>(0.8*max(abs(crossCorr{1}))));
    #
    def get_peaks(self, correlation_output):

        self.debug = False
        expected_distance = 100 # If the dist is greater than this, interpret as another cluster

        filtered_candidates = []
        max_samp = numpy.absolute(correlation_output).max()

        peak_candidates = numpy.nonzero(numpy.absolute(correlation_output) > max_samp*0.80)[0]
        if self.debug:
            print("Values bigger than max*0.80 = ", numpy.absolute(correlation_output)[numpy.absolute(correlation_output) > max_samp*0.95])
            print("Their indices are ", peak_candidates)

        t_peak = None
        for candidate in  peak_candidates:
            if t_peak is None:
                t_peak = candidate

            elif abs(candidate - t_peak) < expected_distance: # They are in the same cluster
                if numpy.absolute(correlation_output[candidate]) > numpy.absolute(correlation_output[t_peak]):
                    t_peak = candidate
            else:
                # candidate belongs to a different cluster
                filtered_candidates.append(t_peak)
                # the first element of next cluster
                t_peak = candidate

        # push the head of last cluster
        filtered_candidates.append(t_peak)

        if self.debug:            print("Candidates: {}", filtered_candidates)

        self.debug = False
        return filtered_candidates


    ## Reads Gold Sequences from a file
    def get_training_signal(self, file_path, number_Tx):

        gold_sequence = []

        # Enumeration starts with 1 in files
        Tx_index = int(number_Tx) + 1

        dir_path = os.path.dirname(os.path.realpath(__file__))

        if self.debug:
            print "Data Path at cor_and_tag block: {}".format(dir_path)


        # Real part of the payload read from 'payload_real.txt' file
        with open( file_path + str(Tx_index) + '_real.txt', 'r') as f:
            pay_real = [line.strip() for line in f]

        length = (len(pay_real))

        # Imaginary part of the payload read from 'payload_imag.txt' file
        with open(file_path + str(Tx_index) + '_imag.txt', 'r') as f1:
            pay_imag = [line.strip() for line in f1]

        # Reconstructing the payload in complex format
        for ii in range(length):
            data_p_c = complex(float(pay_real[ii]), float(pay_imag[ii]))
            data = numpy.complex64(data_p_c)
            gold_sequence.append(data)


        self.log.info("Training Signal {} is successfully retrieved from the target files."
              .format(Tx_index))

        return gold_sequence

    ## Feedback adapters
    def default_csi_feedback(self, channel_estimations):
	#import ipdb;ipdb.set_trace()
	print(channel_estimations)
	self.csi_logger.info('{},{}'.format(int(time.time()*1000000),channel_estimations))
        return channel_estimations

    def calculate_waterfilling_beamweights(self, channel_est):
        ## @todo What happens when one or more channel estimations values are 0?
        self.debug = True
        if self.debug: print "Before WF beamweigts: {}".format(channel_est)
        """ Static Parameters """
        ## @todo should dynamically calculated based on PAYLOAD
        DeltaP = 0
        inc = 0.001
        SINRdb = 20
        Atx = 0
        Gtx = 0
        Noise = 105
        BBPowMax = 6327e+03
        BBPowPayload = 9.1553e-05


        """ Water-filling Algorithm """
        chEst_abs = numpy.absolute(channel_est)  # Channel gain
        w_abs = numpy.zeros(len(channel_est), dtype=float)  # Initialization of weight power
        Niter = 1  # initialize number of total iterations

        ## Check if requested SNR is attainable
        # P_ch = -pow2db(chEst*chEst');
        P_ch = -1*self.__pow2db( # pow2db
            numpy.matmul( # Matrix multiply
                channel_est, # CE array
                numpy.matrix(channel_est).getH() # Complex conjugate
            )
        )

        P_ch = P_ch.item(0,0)


        #BBPowMax_rep = repmat(BBPowPayload*BBPowMax,1,length(channel_estimations));
        BBPowMax_rep = numpy.repeat(BBPowPayload*BBPowMax,len(channel_est))

        #P_tx_offered = pow2db(sum(BBPowMax_rep)) + 30;
        P_tx_offered = self.__pow2db(numpy.sum(BBPowMax_rep)) + 30

        #SNRdb_offered = P_tx_offered + Atx + Gtx - P_ch + Noise;
        SNRdb_offered = P_tx_offered + Atx + Gtx - P_ch + Noise

        if SNRdb_offered < SINRdb:
            if self.debug: print('WARNING - Cannot achieve SNR. {}}vs {}} (dB)'.format(SNRdb_offered,SINRdb))
            if self.debug: print('WARNING - Consider revising Gains\n')
            w_abs = numpy.sqrt(BBPowMax)  # assign maximum

        else:
            # Water filling - power allocation
            targetBB = SINRdb + P_ch - Atx - Gtx - Noise - 30  # in dB (not in dBm, important)
            #print targetBB
            # print numpy.real(targetBB)

            #while pow2db(BBPowPayload*(w_abs*w_abs')) < targetBB


        while (self.__pow2db(BBPowPayload*numpy.matmul(w_abs, numpy.matrix(w_abs).getH()).item(0,0) )) < numpy.real(targetBB):

            # [~,idxvalids] = find(w_abs.^2 + inc < BBPowMax);
            idxvalids = numpy.nonzero(numpy.power(w_abs, 2) + inc < BBPowMax)[0]
            if idxvalids.size == 0:
                break

            # Locate the lowest noise level channel
            index = numpy.argsort(numpy.power(w_abs[idxvalids], 2) + numpy.power(numpy.divide(1, chEst_abs[idxvalids]),2 ))

            # Otherwise go to the next smallest power channel
            w_abs[idxvalids[index[0]]] = w_abs[idxvalids[index[0]]] + inc
            #print('iter {}- Achieved Power = {} (dBm)\n'.format(Niter,pow2db(w_abs*ww_abs')))
            Niter = Niter + 1


        # Assign weights (phase and power)
        beamWeight_angle = numpy.transpose( numpy.multiply(-1, numpy.angle(channel_est)) )         # Phase equalization
        beamWeights =   numpy.multiply(w_abs,
                                      numpy.add(
                                                numpy.cos(beamWeight_angle),
                                                numpy.multiply(
                                                                0+1j,
                                                                numpy.sin(beamWeight_angle))
                                        ))

        if self.debug: print "WF algorith took: {} iterations".format(Niter)
        if self.debug: print "After WF beamweigts: {}".format(beamWeights)
        self.debug = False

        return beamWeights

    def __pow2db(self,a):
        return 10*numpy.log10(a)

    ## Correlation adapter functions
    def numpy_correlation(self, in1, in2):
        return  numpy.correlate(in1, in2, mode='same')

    def signal_fft_correllation(self,in1, in2):
        return signal.correlate(in1, in2, mode='same',method='fft')
"""
 def push_data(self, data_array, output_queue_name):
        print "NOOOooooooooooooooo"
        # np.concatenate((a, b), axis=None)
        if output_queue_name == "output":
            for e in data_array:
                self.output.put(e)
        elif output_queue_name == "correlation_output":
            for e in data_array:
                self.corr_output.put(e)
        else:
            raise Exception("Undefined output queue.")

    def pull_data(self, length, output_queue_name):
        print "NOOOooooooooooooooo"

        data_array = []
        index = 0

        if output_queue_name == "output":

            if self.output.qsize() < length:
                length = self.output.qsize()

            while index < length:
                data_array.append(self.output.get())
                index = index + 1

        elif output_queue_name == "correlation_output":

            if self.corr_output.qsize() < length:
                length = self.corr_output.qsize()

            while index < length:
                data_array.append(self.corr_output.get())
                index = index + 1
        else:
            raise Exception("Undefined output queue.")

        return data_array
        ##numpy.ndarray(shape=(length,),
        #                     buffer=data_array,
        #                     dtype=numpy.complex64)[:length]
"""


"""
    def forecast(self, noutput_items, ninput_items_required):
        
        if self.debug:
            print( "forecast noutput_items: {} \t " \
                        "ninput_items_required: {}"\
                        .format(    noutput_items,
                                    len(ninput_items_required)))

        #setup size of input_items[i] for work call
        for i in range(len(ninput_items_required)):
            ninput_items_required[i] = 6000
        
        if self.debug:
            print( "end of forecast " \
                        "ninput_items_required: {}" \
                        .format( ninput_items_required[0]))

    def general_work(self, input_items, output_items):
        self.log.error("This functu")
        in0 = input_items[0][:len(output_items[0])]
        out = output_items[0]
        # output_items[0][:] = input_items[0]

        self.debug = False
        if self.debug:
            print( "Size of input: {} buffer".format(len(input_items[0])))
            print( "Size of input: {} \t output: {} buffers".format(len(in0), len(out)))

        out[:] = in0

        if self.debug:
            print( "Call for consume function with parameter {}".format(len(input_items[0])))
        self.consume(0, len(input_items[0]))
        #self.consume_each(len(input_items[0]))
        return len(output_items[0])
"""
