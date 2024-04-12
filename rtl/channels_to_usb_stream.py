# Copyright (c) 2021 Hans Baier <hansfbaier@gmail.com>
#
# SPDX-License-Identifier: BSD--3-Clause

from amaranth             import *
from amaranth.build       import Platform
from amaranth.lib.fifo    import SyncFIFO
from luna.gateware.stream import StreamInterface
from util                 import connect_fifo_to_stream

class ChannelsToUSBStream(Elaboratable):
    def __init__(self, max_nr_channels=2, sample_width=24, max_packet_size=256):
        assert sample_width in [16, 24, 32]

        # parameters
        self._max_nr_channels = max_nr_channels
        self._channel_bits    = Shape.cast(range(max_nr_channels)).width
        self._sample_width    = sample_width
        self._fifo_depth      = 2 * max_packet_size

        # ports
        self.no_channels_in      = Signal(self._channel_bits + 1)
        self.channel_stream_in   = StreamInterface(payload_width=self._sample_width, extra_fields=[("channel_nr", self._channel_bits)])
        self.usb_stream_out      = StreamInterface()
        self.audio_in_active     = Signal()
        self.data_requested_in   = Signal()
        self.frame_finished_in   = Signal()

        # debug signals
        self.feeder_state            = Signal()
        self.current_channel         = Signal(self._channel_bits)
        self.level                   = Signal(range(self._fifo_depth + 1))
        self.fifo_read               = Signal()
        self.fifo_full               = Signal()
        self.fifo_level_insufficient = Signal()
        self.done                    = Signal.like(self.level)
        self.out_channel             = Signal(self._channel_bits)
        self.usb_channel             = Signal.like(self.out_channel)
        self.usb_byte_pos            = Signal.like(2)
        self.skipping                = Signal()
        self.filling                 = Signal()

    def elaborate(self, platform: Platform) -> Module:
        m = Module()
        m.submodules.out_fifo = out_fifo = SyncFIFO(width=8 + self._channel_bits, depth=self._fifo_depth, fwft=True)

        channel_stream  = self.channel_stream_in
        channel_valid   = Signal()
        channel_ready   = Signal()

        out_valid        = Signal()
        out_stream_ready = Signal()

        # latch packet start and end
        first_packet_seen   = Signal()
        frame_finished_seen = Signal()

        with m.If(self.data_requested_in):
            m.d.sync += [
                first_packet_seen.eq(1),
                frame_finished_seen.eq(0),
            ]

        with m.If(self.frame_finished_in):
            m.d.sync += [
                frame_finished_seen.eq(1),
                first_packet_seen.eq(0),
            ]

        m.d.comb += [
            self.usb_stream_out.payload.eq(out_fifo.r_data[:8]),
            self.out_channel.eq(out_fifo.r_data[8:]),
            self.usb_stream_out.valid.eq(out_valid),
            out_stream_ready.eq(self.usb_stream_out.ready),
            channel_valid.eq(channel_stream.valid),
            channel_stream.ready.eq(channel_ready),
            self.level.eq(out_fifo.r_level),
            self.fifo_full.eq(self.level >= (self._fifo_depth - 4)),
            self.fifo_read.eq(out_fifo.r_en),
        ]

        with m.If(self.usb_stream_out.valid & self.usb_stream_out.ready):
            m.d.sync += self.done.eq(self.done + 1)

        with m.If(self.data_requested_in):
            m.d.sync += self.done.eq(0)

        current_sample       = Signal(32 if self._sample_width > 16 else 16)
        current_channel      = Signal(self._channel_bits)
        current_byte         = Signal(2 if self._sample_width > 16 else 1)

        m.d.comb += self.current_channel.eq(current_channel),

        bytes_per_sample    = 4
        last_byte_of_sample = bytes_per_sample - 1

        # USB audio still sends 32 bit samples,
        # even if the descriptor says 24
        shift = 8 if self._sample_width == 24 else 0

        out_fifo_can_write_sample = Signal()
        m.d.comb += out_fifo_can_write_sample.eq(
              out_fifo.w_rdy
            & (out_fifo.w_level < (out_fifo.depth - bytes_per_sample)))

        # this FSM handles writing into the FIFO
        with m.FSM(name="fifo_feeder") as fsm:
            m.d.comb += self.feeder_state.eq(fsm.state)

            with m.State("WAIT"):
                m.d.comb += channel_ready.eq(out_fifo_can_write_sample)

                # discard all channels above no_channels_in
                # important for stereo operation
                with m.If(  out_fifo_can_write_sample
                          & channel_valid
                          & (channel_stream.channel_nr < self.no_channels_in)):
                    m.d.sync += [
                        current_sample.eq(channel_stream.payload << shift),
                        current_channel.eq(channel_stream.channel_nr),
                    ]
                    m.next = "SEND"

            with m.State("SEND"):
                m.d.comb += [
                    out_fifo.w_data[:8].eq(current_sample[0:8]),
                    out_fifo.w_data[8:].eq(current_channel),
                    out_fifo.w_en.eq(1),
                ]
                m.d.sync += [
                    current_byte.eq(current_byte + 1),
                    current_sample.eq(current_sample >> 8),
                ]

                with m.If(current_byte == last_byte_of_sample):
                    m.d.sync += current_byte.eq(0)
                    m.next = "WAIT"


        channel_counter = Signal.like(self.no_channels_in)
        byte_pos        = Signal(2)
        first_byte      = byte_pos == 0
        last_byte       = byte_pos == 3

        with m.If(out_valid & out_stream_ready):
            m.d.sync += byte_pos.eq(byte_pos + 1)

            with m.If(last_byte):
                m.d.sync += channel_counter.eq(channel_counter + 1)
                with m.If(channel_counter == (self.no_channels_in - 1)):
                    m.d.sync += channel_counter.eq(0)

        with m.If(self.data_requested_in):
            m.d.sync += channel_counter.eq(0)

        fifo_level_sufficient = Signal()
        m.d.comb += [
            self.usb_channel.eq(channel_counter),
            self.usb_byte_pos.eq(byte_pos),
            fifo_level_sufficient.eq(out_fifo.level >= (self.no_channels_in << 2)),
            self.fifo_level_insufficient.eq(~fifo_level_sufficient),
        ]

        with m.If(self.frame_finished_in):
            m.d.sync += byte_pos.eq(0)

        # this FSM handles reading fron the FIFO
        # this FSM provides robustness against
        # short reads. On next frame all bytes
        # for nonzero channels will be discarded until
        # we reach channel 0 again.
        with m.FSM(name="fifo_postprocess") as fsm:
            with m.State("NORMAL"):
                m.d.comb += [
                    out_fifo.r_en.eq(self.usb_stream_out.ready),
                    out_valid.eq(out_fifo.r_rdy)
                ]

                with m.If(~self.audio_in_active & out_fifo.r_rdy):
                    m.next = "DISCARD"

                # frame ongoing
                with m.Elif(~frame_finished_seen):
                    # start filling if there are not enough enough samples buffered
                    # for one channel set of audio samples
                    last_channel = self.out_channel == (self._max_nr_channels - 1)

                    with m.If(last_byte & last_channel & ~fifo_level_sufficient):
                        m.next = "FILL"

                    with m.If((self.out_channel != channel_counter)):
                        m.d.comb += [
                            out_fifo.r_en.eq(0),
                            self.usb_stream_out.payload.eq(0),
                            out_valid.eq(1),
                            self.filling.eq(1),
                        ]

                # frame finished: discard extraneous samples
                with m.Else():
                    with m.If(out_fifo.r_rdy & (self.out_channel != 0)):
                        m.d.comb += [
                            out_fifo.r_en.eq(1),
                            out_valid.eq(0),
                        ]
                        m.d.sync += [
                            frame_finished_seen.eq(0),
                            byte_pos.eq(0),
                        ]
                        m.next = "DISCARD"

            with m.State("DISCARD"):
                with m.If(out_fifo.r_rdy):
                    m.d.comb += [
                        out_fifo.r_en.eq(1),
                        out_valid.eq(0),
                        self.skipping.eq(1),
                    ]
                    with m.If(self.audio_in_active & (self.out_channel == 0)):
                        m.d.comb += out_fifo.r_en.eq(0)
                        m.next = "NORMAL"

            with m.State("FILL"):
                channel_is_ok = fifo_level_sufficient & (self.out_channel == channel_counter)
                with m.If(self.frame_finished_in | channel_is_ok):
                    m.next = "NORMAL"
                with m.Else():
                    m.d.comb += [
                        out_fifo.r_en.eq(0),
                        self.usb_stream_out.payload.eq(0),
                        out_valid.eq(1),
                        self.filling.eq(1),
                    ]

        return m
