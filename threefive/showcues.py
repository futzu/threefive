"""
showcues.py aka threefive hls
"""

import datetime
import sys
import time
from collections import deque
from m3ufu import M3uFu, TagParser, HEADER_TAGS
from new_reader import reader
from .segment import Segment
from .cue import Cue
from .stuff import print2

REV = "\033[7m"
NORM = "\033[27m"
# REV = ""
# NORM = ""
SUB = "\t\t\t"
NSUB = f"\n{SUB}"
ROLLOVER = 95443.717678
HEADER_TAGS = list(HEADER_TAGS)
HEADER_TAGS.append("#EXTM3U")


def atoif(value):
    """
    atoif converts ascii to (int|float)
    """
    if isinstance(value, str):
        try:
            value = float(value)
        except:
            try:
                value = int(value)
            finally:
                return value
    return value


def iso8601():
    """
    return UTC time in iso8601 format.

    '2023-05-11T15:55:51.'

    """
    return f"{datetime.datetime.utcnow().isoformat()[:-4]}Z "


class Scte35Profile:
    """
    Scte35Profile Manages the Scte35 Parsing Profile
    """

    def __init__(self):
        """
        A Scte35Profile
        """
        self.expand_cues = False  # Show SCTE-35 Cues fully expanded.
        self.parse_segments = True  # Parse Segments for SCTE-35.
        self.parse_manifests = True  # Parse m3u8 files for SCTE-35 HLS tags.
        self.hls_tags = [
            "#EXT-OATCLS-SCTE35",
            "#EXT-X-DATERANGE",
            "#EXT-X-SCTE35",
            "#EXT-X-CUE-OUT",
            "#EXT-X-CUE-OUT-CONT",
            "#EXT-X-CUE-IN",
        ]  #  Parse these types of HLS SCTE-35 tags.
        self.command_types = [6, 5]  # Which SCTE-35 Commands to parse.
        self.descriptor_tags = [
            2,
        ]  # Which Descriptors to parse.
        # Which Descriptor Segmentation Types IDs should be parsed
        self.starts = [0x22, 0x30, 0x32, 0x34, 0x36, 0x44, 0x46]
        self.seg_type = 0x23

    def _mk_line(self, k, v):
        line = f"{k} = "
        if isinstance(v, list):
            for item in v:
                if isinstance(item, int):
                    line = f"{line}{hex(item)},"
                else:
                    line = f"{line}{item},"
        if isinstance(v, bool):
            line = f"{line}{v}"
        if line.endswith(","):
            line = line[:-1]
        return line

    def write_profile(self, pro_file):
        """
        write_profile writes .35rc for editing.
        """
        with open(pro_file, "w") as pro_f:
            for que, vee in vars(self).items():
                line = self._mk_line(que, vee)
                pro_f.write(line + "\n")
            print("\ncreated .35rc\n")

    def show_profile(self, headline):
        """
        show_profile displays profile settings.
        """
        print(f"\n\n\t\t\t{REV}{headline}{NORM}\n")
        for que, vee in vars(self).items():
            if isinstance(vee, list):
                if isinstance(vee[0], int):
                    vee = [hex(eye) for eye in vee]
            print(f"\t\t\t{que} = {vee}\n")
            time.sleep(0.3)

    def clean_n_split(self, line):
        """
        clean_n_split a line.
        """
        this, that = None, None
        bad = [" ", "\n", "\t", '"', "'"]
        for bee in bad:
            line = line.replace(bee, "")
        if line:
            this, that = line.split("=", 1)
            that = list(that.split(","))
        if line.startswith("#") or line.startswith("//"):
            this = None
        return this, that

    def _chk_booleans(self,this, that):
        booleans=["expand_cues","parse_segments","parse_manifests"]
        if this in booleans:
            pre_that =True
            if that.lower=='false':
                pre_that=False
            that =pre_that
        return this,that

    def _chk_lists(self,this,that):
        if this in ["command_types", "descriptor_tags", "starts"]:
            new_that = []
            for s in that:
                if s.lower().startswith("0x"):
                    new_that.append(int(s, 16))
                else:
                    new_that.append(int(s))
            that = new_that
            return this,that

    def format4profile(self, this, that):
        """
        format4profile formats data read from .35rc for internal use.
        """
        if this is None or that is None:
            return
        this,that= self._chk_booleans(this,that)
        this,that = self.chk_lists(this,that)
        self.__dict__.update({this: that})

    def read_profile(self, pro_file):
        """
        read_profile reads .35rc
        """
        try:
            with open(pro_file, "r") as pro_file:
                for line in pro_file:
                    this, that = self.clean_n_split(line)
                    self.format4profile(this, that)
        except:
            pass
        finally:
            self.show_profile("Profile:")

    def set_pts(self, cue):
        """
        set_pts cue.command.pts_time +
        cue.info_section.pts_adjustment
        % ROLLOVER
        """
        pts = cue.command.pts_time + cue.info_section.pts_adjustment
        return pts % ROLLOVER

    def validate_cue(self, cue):
        """
        validate_cue use the parsing profile to validate a SCTE-35 Cue.
        """
        pts = None
        line = None
        cue.decode()
        if cue.command.command_type in self.command_types:
            if "pts_time" in vars(cue.command) and cue.command.pts_time:
                pts = self.set_pts(cue)
            if self.expand_cues:
                cue.show()
            if cue.command.command_type == 5:
                line = self.validate_splice_insert(cue)
        if cue.command.command_type == 6:
            line = self.validate_time_signal(cue)
        return pts, line

    def validate_splice_insert(self, cue):
        """
        validate_splice_insert is named appropriately.
        """
        line = None
        if cue.command.out_of_network_indicator:
            if "break_duration" in vars(cue.command) and cue.command.break_duration:
                duration = cue.command.break_duration
                line = f"#EXT-X-CUE-OUT:{duration}\n"
                return line
        else:
            line = "#EXT-X-CUE-IN\n"
            return line
        return line

    def _dscptr_duration(self, dscptr, line):
        if "segmentation_duration" in vars(dscptr):
            duration = dscptr.segmentation_duration
            line = f"#EXT-X-CUE-OUT:{duration}\n"
        return line

    def _dscptr_is_start(self, dscptr, line):
        if dscptr.segmentation_type_id in self.starts:
            self.seg_type = dscptr.segmentation_type_id + 1
            line = self._dscptr_duration(dscptr, line)
        return line

    def _dscptr_is_stop(self, dscptr, line):
        if dscptr.segmentation_type_id == self.seg_type:
            line = "#EXT-X-CUE-IN\n"
            self.seg_type = None
        return line

    def _line_from_dscptr(self, dscptr):
        line = None
        if dscptr.tag in self.descriptor_tags:
            line = self._dscptr_is_start(dscptr, line)
            line = self._dscptr_is_stop(dscptr, line)
        return line

    def validate_time_signal(self, cue):
        """
        validate_time_signal is named appropriately.
        """
        for dscptr in cue.descriptors:
            line = self._line_from_dscptr(dscptr)
            if line:
                return line
        return None


class Pane:
    """
    Pane class. Sliding_Window slides Panes
    """

    def __init__(self, media, lines):
        self.media = media
        self.lines = lines

    def get(self):
        """
        get merges self.lines and self.media for
        writing m3u8 files.
        """
        all_lines = self.lines + [self.media]
        return "".join(all_lines)


class SlidingWindow:
    """
    The Sliding Window class
    """

    def __init__(self, size=101):
        self.size = size
        self.panes = deque()
        self.delete = False

    def pop_pane(self):
        """
        pop_pane removes the first item in self.panes
        """
        if len(self.panes) > self.size:
            self.panes.popleft()

    def all_panes(self):
        """
        all_panes returns the current window panes joined.
        """
        return "\n".join([a_pane.get() for a_pane in self.panes])

    def slide_panes(self, a_pane):
        """
        slide calls self.push_pane with a_pane
        and then calls self.pop_pane to trim self.panes
        as needed.
        """
        self.pop_pane()
        self.panes.append(a_pane)


class AacParser:
    """
    AacParser parses aac segments.
    """

    applehead = b"com.apple.streaming.transportStreamTimestamp"

    @staticmethod
    def is_header(header):
        """
        is_header tests aac and ac3 files for ID3 headers.
        """
        if header[:3] == b"ID3":
            return True
        return False

    @staticmethod
    def id3_len(header):
        """
        id3_len parses the length value from ID3 headers
        """
        id3len = int.from_bytes(header[6:], byteorder="big")
        return id3len

    @staticmethod
    def syncsafe5(somebytes):
        """
        syncsafe5 parses PTS from ID3 tags.
        """
        lsb = len(somebytes) - 1
        syncd = 0
        for idx, bite in enumerate(somebytes):
            syncd += bite << ((lsb - idx) << 3)
        return round(syncd / 90000.0, 6)

    def parse(self, media):
        """
        aac_pts parses the ID3 header tags in aac and ac3 audio files
        """
        pts = 0
        aac = reader(media)
        header = aac.read(10)
        if self.is_header(header):
            id3len = self.id3_len(header)
            data = aac.read(id3len)
            if self.applehead in data:
                try:
                    pts = float(data.split(self.applehead)[1].split(b"\x00", 2)[1])
                except:
                    pts = self.syncsafe5(data.split(self.applehead)[1][:9])
        return round((pts % ROLLOVER), 6)


class CuePuller:
    """
    CuePuller is the main object.
    """

    def __init__(self):
        self.media = deque()
        self.sidecar = "35.sidecar"
        self.dumpfile = "35.dump"
        self.last_dump_line = None
        self.m3u8 = "35.m3u8"
        self.base_uri = None
        self.iv = None
        self.key_uri = None
        self.last_iv = None
        self.last_key_uri = None
        self.break_timer = None
        self.break_duration = None
        self.reload = True
        self.sleep_duration = 0
        self.window_size = None
        self.sliding_window = SlidingWindow()
        self.cue_state = None
        self.last_cue = None
        self.headers = []
        self.pts = 0
        self.cont_resume = False
        self.first_segment = True
        self.hls_pts = "HLS"
        self.flat = "35flat.m3u8"
        self.prof = Scte35Profile()
        self.pro_file = ".35rc"
        self.prof.read_profile(self.pro_file)
        self.clear_files()

    @staticmethod
    def clear():
        """
        clear previous line.
        """
        print(" " * 80, end="\r")
        print(" " * 80, file=sys.stderr, end="\r", flush=True)

    def clear_files(self):
        """
        clear_files clobbers the appended files
        self.sidecar, self.dumpfile, self.flat, self.m3u8
        when showcues is started.
        """
        for sidef in [self.sidecar, self.dumpfile, self.flat, self.m3u8]:
            with open(sidef, "w+") as side_file:  # touch
                pass

    def chk_aes(self, line):
        """
        chk_aes checks for AES encryption
        """
        if "#EXT-X-KEY" in line:
            tags = TagParser([line]).tags
            if "URI" in tags["#EXT-X-KEY"]:
                self.key_uri = tags["#EXT-X-KEY"]["URI"]
                if not self.key_uri.startswith("http"):
                    re_uri = self.base_uri + self.key_uri
                    self.key_uri = re_uri
                if "IV" in tags["#EXT-X-KEY"]:
                    self.iv = tags["#EXT-X-KEY"]["IV"]

    def to_sidecar(self, pts, line):
        """
        to_sidecar writes (pts,hls tag) pairs to the sidecar file.
        """
        with open(self.sidecar, "a") as sidecar:
            sidecar.write(f"{round(pts,6)},{line}\n")

    def to_dump(self, pts, line):
        """
        to_dump copies all SCTE-35 lines to self.dumpfile.
        """
        with open(self.dumpfile, "a") as dump:
            dump_line = f"{pts},{line}\n"
            if dump_line != self.last_dump_line:
                dump.write(dump_line)
                self.last_dump_line = dump_line

    def media_stuff(self):
        """
        media_stuff trims segment URI to just the file name.
        """
        media = self.media[-1]
        short_media = media.rsplit("/", 1)[1].split("?", 1)[0]
        return f"Media: {short_media.strip()}"

    def cue_stuff(self):
        """
        cue_stuff returns self.cue_state formated.
        """
        return f"Cue {REV}{self.cue_state} {NORM}"

    def diff_stuff(self):
        """
        diff stuff returns formated self.break_timer
        and if possible the difference between the actual break duration
        and the specified SCTE-35 break duration.
        """
        if self.break_timer is not None:
            if not self.break_duration:
                return f"{NSUB}Break Timer: {round(self.break_timer,6)}"
            return (NSUB).join(
                [
                    f"{NSUB}Timer: { round(self.break_timer,6)}",
                    f"Duration: {self.break_duration}",
                    f"Diff: {round(self.break_timer - self.break_duration,6)}",
                ]
            )
        return ""

    def dur_stuff(self):
        """
        dur_stuff returns self.break_duration formated.
        """
        return f"{NSUB}Duration: {self.break_duration}"

    def pts_stuff(self):
        """
        pts_stuff returns  PTS formated.
        """
        return f"{NSUB}{self.hls_pts}: {self.pts}"

    def _set_out(self, line, head):
        if line.startswith("#EXT-X-CUE-OUT") and self.cue_state in [None, "IN"]:
            self.reset_break()
            self.cue_state = "OUT"
            self.break_timer = 0.0
            if ":" in line:
                self.break_duration = atoif(line.split(":")[1])
            self.to_sidecar(self.pts, line)
            self.clear()
            print(f"{head}{self.dur_stuff()}{NSUB}{self.media_stuff()}\n")

    def _set_in(self, line, head):
        if line.startswith("#EXT-X-CUE-IN") and self.cue_state == "CONT":
            self.cue_state = "IN"
            self.to_sidecar(self.pts, line)
            self.clear()
            print(f"{head}{self.diff_stuff()}{NSUB}{self.media_stuff()}\n")
            self.reset_break()

    def set_cue_state(self, cue, line):
        """
        set_cue_state determines cue_state

        """
        if cue.encode() == self.last_cue:
            return ""
        self.last_cue = cue.encode()
        if "CONT" not in line:
            head = f"\n{iso8601()}{REV}{line}{NORM}{self.pts_stuff()} (Splice Point)"
            self._set_in(line, head)
            self._set_out(line, head)
        if "CONT" in line and self.cue_state in ["OUT", "CONT"]:
            self.to_sidecar(self.pts, line)
            self.cue_state = "CONT"
        return line

    def invalid(self, line):
        """
        invalid print invalid SCTE-35 HLS tags
        """
        self.clear()
        print(
            f"\n{iso8601()}{REV} Skipped {NORM}  {line}{self.pts_stuff()}{NSUB}{self.media_stuff()}\n"
        )
        return "## " + line

    def show_tags(self, tags):
        try:
            for que, vee in tags.items():
                print(f"{SUB}{que}: {vee}")
        except:
            return

    def _set_break_timer(self, line, cont_tags):
        """
        _set_break_timer sets self.break_timer to ElaspsedTime
        read from a CUE-OUT-CONT tag or to 0.0.
        """
        if self.break_timer:
            return
        if "ElapsedTime" in cont_tags:
            self.break_timer = cont_tags["ElapsedTime"]
        else:
            try:
                self.break_timer = round(float(line.split(":", 1)[1].split("/")[0]), 3)
            except:
                self.break_timer = 0.0
        print(f"{iso8601()}{REV} Break Timer {NORM}to {self.break_timer}\n")
        time.sleep(0.1)

    def _set_break_duration(self, line, cont_tags):
        """
        __set_break_duration sets self.break_duration from
        a CUE-OUT-CONT tag or from a CUE-OUT tag.
        """
        if self.break_duration:
            return
        if "Duration" in cont_tags:
            self.break_duration = cont_tags["Duration"]
        else:
            try:
                self.break_duration = round(
                    float(line.split(":", 1)[1].split("/")[1]), 3
                )
            except:
                self.break_duration = None
        if self.break_duration:
            print(f"{iso8601()}{REV}Break Duration {NORM}to {self.break_duration}\n")
            time.sleep(0.1)

    def chk_x_cue_out_cont(self, tags, line):
        """
        chk_x_cue_out_const processes
        #EXT-X-CUE-OUT-CONT tags
        """
        cont_tags = tags["#EXT-X-CUE-OUT-CONT"]
        if self.cue_state not in ["OUT", "CONT"] and not self.first_segment:
            return None
        if self.first_segment:
            print(f"{iso8601()}{REV} Resuming Ad Break {NORM}\n")
            self.cue_state = "CONT"
            self._set_break_timer(line, cont_tags)
            self._set_break_duration(line, cont_tags)
        return self.auto_cont()

    def chk_x_cue_in(self, tags, line):
        """
        chk_x_cue_in processes
        #EXT-X-CUE-IN tags.
        """
        return self.set_cue_state(line, line)

    def chk_x_cue_out(self, tags, line):
        """
        chk_x_cue_out processes
        #EXT-X-CUE-OUT tags
        """
        return self.set_cue_state(line, line)

    def chk_x_scte35(self, tags, line):
        """
        chk_x_scte35 handles #EXT-X-SCTE35 tags.
        """
        if "CUE" in tags["#EXT-X-SCTE35"]:
            cue = Cue(tags["#EXT-X-SCTE35"]["CUE"])
            pts, new_line = self.prof.validate_cue(cue)
            if pts and new_line:
                return self.set_cue_state(tags["#EXT-X-SCTE35"]["CUE"], new_line)
        return self.invalid(line)

    def _x_daterange_in_out(self, tag, dtags):
        if scte35_tag in dtags:
            cue = Cue(dtags[scte35_tag])
            pts, new_line = self.prof.validate_cue(cue)
            if pts and new_line:
                return self.set_cue_state(
                    tags["#EXT-X-DATERANGE"][scte35_tag], new_line
                )
        return False

    def chk_x_daterange(self, tags, line):
        """
        chk_x_daterange handles #EXT-X-DATERANGE tags.
        """
        self.show_tags(tags["#EXT-X-DATERANGE"])
        for scte35_tag in ["SCTE35-OUT", "SCTE35-IN"]:
            cue_state = self._x_daterange_in_out(scte35tag, tags["#EXT-X-DATERANGE"])
            if cue_state:
                return cue_state
        return self.invalid(line)

    def chk_x_oatcls(self, tags, line):
        """
        chk_x_oatcls handles
        #EXT-OATCLS-SCTE35
        HLS tags.
        """
        cue = Cue(tags["#EXT-OATCLS-SCTE35"])
        pts, new_line = self.prof.validate_cue(cue)
        if pts and new_line:
            if abs(pts - self.pts) > 5:  # Handle Cues out of sync with video PTS
                pts = self.pts
            return self.set_cue_state(tags["#EXT-OATCLS-SCTE35"], new_line)
        return self.invalid(line)

    def scte35(self, line):
        """
        scte35 processes SCTE-35 related tags.
        """
        scte35_map = {
            "#EXT-X-DATERANGE": self.chk_x_daterange,
            "#EXT-X-SCTE35": self.chk_x_scte35,
            "#EXT-X-CUE-OUT-CONT": self.chk_x_cue_out_cont,
            "#EXT-OATCLS-SCTE35": self.chk_x_oatcls,
            "#EXT-X-CUE-IN": self.chk_x_cue_in,
            "#EXT-X-CUE-OUT": self.chk_x_cue_out,
        }
        tags = TagParser([line]).tags
        for key in scte35_map.keys():
            if key in line:
                self.to_dump(self.pts, line)
        if self.prof.parse_manifests:
            for que, vee in scte35_map.items():
                if que in line:
                    if que not in self.prof.hls_tags:
                        return None
                    return vee(tags, line)
        return line

    def auto_cont(self):
        self.cue_state = "CONT"
        line = (
            f"#EXT-X-CUE-OUT-CONT:{round(self.break_timer,3)}/{self.break_duration}\n"
        )
        line = self.set_cue_state(line, line)
        return line

    def auto_cuein(self, line):
        """
        auto_cuein handles cue.command.auto-return
        """
        if self.cue_state == "CONT":
            if self.break_timer and self.break_duration:
                if self.break_timer >= self.break_duration:
                    self.cue_state = "IN"
                    self.clear()
                    print(
                        f"{iso8601()}{REV} AUTO CUE-IN {NORM}{self.pts_stuff()}{self.diff_stuff()}{NSUB}{self.media_stuff()}\n"
                    )
                    self.reset_break()
                    self.to_sidecar(self.pts, "#AUTO\n#EXT-X-CUE-IN\n")
                    return "#AUTO\n#EXT-X-CUE-IN\n" + line
        return line

    def reset_break(self):
        """
        reset_break resets
        break_duration, break_timer,
        and cue_state after a CUE-IN
        """
        if self.cue_state == "IN":
            self.break_duration = None
            self.break_timer = None
            self.cue_state = None

    def extinf(self, line):
        """
        extinf parses lines that start with #EXTINF
        for the segment duration.
        """
        tags = TagParser([line]).tags
        if "#EXTINF" in tags:
            if isinstance(tags["#EXTINF"], str):
                tags["#EXTINF"] = tags["#EXTINF"].rsplit(",", 1)[0]
            seg_time = round(atoif(tags["#EXTINF"]), 6)
            line = self.auto_cuein(line)
            if self.pts is not None:
                self.pts += seg_time
            if self.break_timer is not None:
                self.break_timer += seg_time
        return line

    def print_time(self):
        """
        print_time prints wall clock and pts.
        """
        stuff = ""
        if self.break_timer:
            stuff = f"{REV} Break {NORM} {round(self.break_timer,3)}"
            if self.break_duration:
                stuff = f"{stuff} / {round(self.break_duration,3)}"
        print(
            f"\r\r{iso8601()}{REV} {self.hls_pts} {NORM} {self.pts} {stuff}",
            end="\r",
            file=sys.stderr,
            flush=True,
        )

    def ts_pts(self, seg):
        """
        ts_pts set pts from segment
        """
        if seg.pts_start:
            self.pts = seg.pts_start
            self.print_time()
            self.hls_pts = "PTS"

    def ts_cues(self, seg):
        """
        ts_cues process SCTE-35 cues
        found in a segment.
        """
        for cue in seg.cues:
            if "pts" in vars(cue.packet_data) and cue.packet_data.pts:
                self.pts = cue.packet_data.pts
            if cue.encode() != self.last_cue:
                self.last_cue = cue.encode()
                self.ts_set_cue(cue)

    def ts_set_cue(self, cue):
        """
        ts_set_cue validate and set cue from ts segment.
        """
        cue_pts, line = self.prof.validate_cue(cue)
        if cue_pts and line:
            self.set_cue_state(cue.encode(), line)
            self.clear()
            print(
                (NSUB).join(
                    [
                        f"\n{iso8601()}{REV} SCTE-35 {NORM}",
                        f"Stream PTS: {round(self.pts,6)}",
                        f"PreRoll: {round(cue_pts - self.pts,6)}",
                        f"Splice Point: {round(cue_pts,6)}",
                        f"Type: {cue.command.name}",
                        f"{self.media_stuff()}\n",
                    ]
                )
            )

    def chk_ts(self, this):
        """
        chk_ts  check MPEGTS for PTS and SCTE-35.
        """
        if ".ts" in this:
            if self.first_segment:
                Segment(this, key_uri=self.key_uri, iv=self.iv).show()
            seg = Segment(this, key_uri=self.key_uri, iv=self.iv)
            seg.shushed()
            seg.decode()
            self.ts_pts(seg)
            if self.prof.parse_segments:
                self.ts_cues(seg)
            self.print_time()

    def chk_aac(self, this):
        """
        chk_aac check aac and ac3  HLS audio segments
        for PTS in ID3 header tags.
        """
        if ".aac" in this or ".ac3" in this:
            aac_parser = AacParser()
            pts = aac_parser.parse(this)
            if pts:
                self.pts = pts
                self.hls_pts = "PTS"
                self.print_time()

    def new_media(self, this):
        """
        new_media check to see
        if the media is new in a
        live sliding window
        """
        if this not in self.media:
            self.media.append(this)
            if len(self.media) > self.window_size + 1:
                self.media.popleft()
            return True
        return False

    def parse_target_duration(self, line):
        """
        parse_target_duration reads target duration
        off the manifest to set self.sleep_duration.
        self.sleep_duration is used to throttle manifest
        requests.
        """
        if "TARGETDURATION" in line:
            if self.sleep_duration == 0:
                target_duration = atoif(line.split(":")[1])
                self.sleep_duration = round(target_duration * 0.5, 3)
                print(f"{SUB}{REV} Target Duration {NORM} {target_duration}\n")

    def mk_window_size(self, lines):
        """
        mk_window_size sets the sliding window size
        for the output to match that off the input and
        determine how long to keep media data info
        for segments.
        """
        if not self.window_size:
            self.window_size = len([line for line in lines if "#EXTINF:" in line])
            self.sliding_window.size = self.window_size
            print(f"{SUB}{REV} Window Size {NORM} {self.window_size}\n")

    def update_cue_state(self):
        """
        update_cue_state changes CUE state.
        """
        if self.cue_state == "OUT":
            self.cue_state = "CONT"
        if self.cue_state == "IN":
            self.cue_state = None

    @staticmethod
    def decode_lines(lines):
        """
        decode_lines convert bytes to ascii
        """
        return [line.decode() for line in lines]

    def parse_line(self, line):
        if "#EXT-X-PROGRAM-DATE-TIME" in line:
            return None

        if "#EXTINF:" in line:
            line = self.extinf(line)
            return line
        self.chk_aes(line)
        line = self.scte35(line)
        return line

    def parse_header(self, line):
        """
        parse_headers parses m3u8 files for HLS header tags.
        """
        if "#EXT-X-PROGRAM-DATE-TIME" in line:
            return False
        splitline = line.split(":", 1)
        if splitline[0] in HEADER_TAGS:
            self.parse_target_duration(line)
            self.headers.append(line)
            return True
        return False

    def chk_endlist(self, line):
        """
        chk_endlist disables manifest reloading
        if line contains ENDLIST tag.
        """
        if "#EXT-X-ENDLIST" in line:
            self.reload = False

    def write_flat(self, lines, media):
        """
        write_flat flatten out the sliding window
        and write all data to flat.m3u8.
        """
        with open(self.flat, "a") as flat:
            if self.first_segment:
                flat.write("#EXTM3U\n")
                for header in self.headers:
                    flat.write(header)
            for line in lines:
                flat.write(line)
            flat.write(media)

    def write_manifest(self):
        """
        write_manifest write data to 35.m3u8
        with profile rules applied.
        """
        with open(self.m3u8, "w") as out:
            out.write("#EXTM3U\n")
            out.write("".join(self.headers))
            out.write(self.sliding_window.all_panes())

    def _parse_new_media(self, lines, media):
        self.write_flat(lines, media)
        parsed = [self.parse_line(line) for line in lines]
        lines = [line for line in parsed if line is not None]
        media = media.replace("\n", "")
        self.chk_ts(media)
        self.chk_aac(media)
        pane = Pane(media, lines)
        self.sliding_window.slide_panes(pane)
        self.first_segment = False

    def _fixup_media(self, lines, media):
        if not media.startswith("http"):
            media = self.base_uri + "/" + media
        if self.new_media(media):
            self._parse_new_media(lines, media)

    def _post_parse(self):
        self.write_manifest()
        self.headers = []
        self.update_cue_state()
        time.sleep(self.sleep_duration)

    def _parse_manifest(self, manifest):
        """
        _parse_manifest, parses m3u8 files.
        """
        if manifest in ['hls']:
            sys.argv.remove('hls')
            return False
        with reader(manifest) as m3u8:
            lines = []
            m3u8_lines = self.decode_lines(m3u8.readlines())
            self.mk_window_size(m3u8_lines)
            for line in m3u8_lines:
                self.chk_endlist(line)
                if line.startswith("#"):
                    if not self.parse_header(line):
                        lines.append(line)
                else:
                    media = line
                    self._fixup_media(lines, media)
                    lines = []
            self._post_parse()

    def pull(self, manifest):
        """
        pull m3u8 and parse it.
        """
        print(f"\n{iso8601()}{REV} Started {NORM}\n")
        print(f"{SUB}{REV} Manifest {NORM} {manifest}\n")
        self.base_uri = manifest.rsplit("/", 1)[0]
        self.sliding_window = SlidingWindow()
        while self.reload:
            self._parse_manifest(manifest)
        with open(self.flat, "a") as flat:
            flat.write("#EXT-X-ENDLIST\n")


def _clean_args():
    args = sys.argv
    if "hls" in args:
        args.remove("hls")
    if "help" in args:
        print(helpme)
        sys.exit()
    if "profile" in args:
        scp = Scte35Profile()
        scp.write_profile(".35rc")
        sys.exit()
    return args

def cli():
    """
    cli is a function to use in a command line tool

        #!/usr/bin/env python3

        from showcues import cli

        if __name__ == "__main__":
            cli()


     is all that's required.
    """
    playlists = None
    m3u8 = None
    args=_clean_args()
    with reader(args[-1]) as arg:
        variants = [line for line in arg if b"#EXT-X-STREAM-INF" in line]
        if variants:
            fumo = M3uFu()
            fumo.m3u8 = args[1]
            fumo.decode()
            playlists = [
                segment
                for segment in fumo.segments
                if "#EXT-X-STREAM-INF" in segment.tags
            ]
    if playlists:
        m3u8 = playlists[0].media
    else:
        m3u8 = sys.argv[-1]
    cpulr = CuePuller()
    cpulr.pull(m3u8)
    print()
    sys.exit()


helpme = """

[ threefive hls ]

[ Help ]
    To display this help:

	threefive hls help

[ Input ]
    threefive hls takes an m3u8 URI as input.

    M3U8 formats supported:
        * master  ( When a master.m3u8 used,
                   threefive hls parses the first rendition it finds )
        * rendition
    Segment types supported:
    * AAC
    * AC3
    * MPEGTS
    *codecs:
        * video
            * mpeg2, h.264, h.265
        * audio
            * mpeg2, aac, ac3, mp3

    Protocols supported:
    * file
    * http(s)
    * UDP
    * Multicast

    Encryption supported:
    * AES-128 (segments are automatically decrypted)

[ SCTE-35 ]
    threefive hls displays SCTE-35 Embedded Cues as well as SCTE-35 HLS Tags.

    Supported SCTE-35:
    * All Commands, Descriptors, and UPIDS
      in the 2022-b SCTE-35 specification.

    Supported HLS Tags
    * #EXT-OATCLS-SCTE35
    * #EXT-X-CUE-OUT-CONT
    * #EXT-X-DATERANGE
    * #EXT-X-SCTE35
    * #EXT-X-CUE-IN
    * #EXT-X-CUE-OUT


[ SCTE-35 Parsing Profiles ]
    SCTE-35 parsing can be fine tuned by setting a parsing profile.

    running the command:

            threefive hls profile

    will generate a default profile and write a file named .35rc
    in the current working directory.

    a@fu:~$ cat .35rc

    expand_cues = False
    parse_segments = False
    parse_manifests = True
    hls_tags = #EXT-OATCLS-SCTE35,#EXT-X-CUE-OUT-CONT,
    #EXT-X-DATERANGE,#EXT-X-SCTE35,#EXT-X-CUE-IN,#EXT-X-CUE-OUT
    command_types = 0x6,0x5
    descriptor_tags = 0x2
    starts = 0x22,0x30,0x32,0x34,0x36,0x44,0x46

    ( Integers are show in hex (base 16),
      base 10 unsigned integers can also be used in .35rc )

    * expand_cues:       set to True to show cues fully expanded as JSON
    * parse_segments:    set to true to enable parsing SCTE-35 from MPEGTS.
    * parse_manifests:   set to true to parse the m3u8 file for SCTE-35 HLS Tags.
    * hls_tags:          set which SCTE-35 HLS Tags to parse.
    * command_types:     set which Splice Commands to parse.
    * descriptor_tags:   set which Splice Descriptor Tags to parse.
    * starts:            set which Segmentation Type IDs to use to start breaks.

    Edit the file as needed and then run threefive hls.

[ Profile Formatting Rules ]
    * Values do not need to be quoted.
    * Multiple values are separated by a commas.
    * No partial line comments. Comments must be on a separate lines.
    * Comments can be started with a # or //
    * Integers can be base 10 or base 16

[ Output Files ]
    * Created in the current working directory
    * Clobbered on start of showcues
    * Profile rules applied to the output:
        * 35.m3u8  - live playable rewrite of the m3u8
        * 35.sidecar - list of ( pts, HLS SCTE-35 tag ) pairs
    * Profile rules not applied to the output:
        * 35.dump  -  all of the HLS SCTE-35 tags read.
        * 35.flat  - every time an m3u8 is reloaded,
                     it's contents are appended to 35.flat.

[ Cool Features ]
    * threefive hls can resume when started in the middle of an ad break.

            2023-10-13T05:59:50.24Z Resuming Ad Break
            2023-10-13T05:59:50.34Z Setting Break Timer to 17.733
            2023-10-13T05:59:50.44Z Setting Break Duration to 60.067

    * mpegts streams are listed on start ( like ffprobe )

        Program: 1
            Service:
            Provider:
            Pid:	480
            Pcr Pid:	481
            Streams:
                Pid: 481[0x1e1]	Type: 0x1b AVC Video
                Pid: 482[0x1e2]	Type: 0xf AAC Audio
                Pid: 483[0x1e3]	Type: 0x86 SCTE35 Data
                Pid: 484[0x1e4]	Type: 252 Unknown
                Pid: 485[0x1e5]	Type: 0x15 ID3 Timed Meta Data

[ Example Usage ]

	* Show this help:   threefive hls help

	* Generate a new .35rc:   threefive hls profile

	* parse an m3u8:    threefive hls  https://example.com/out/master.m3u8

"""


if __name__ == "__main__":
    cli()
