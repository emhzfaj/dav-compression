import customtkinter as ctk
from tkinter import messagebox
import subprocess
import threading
import queue
import os
import sys
import time
import psutil
import json
import math
import shutil
import fnmatch

class CRFWithVBVCompressor:
    """
    Speed-optimized video compression using CRF with VBV constraints
    Enhanced for faster processing while maintaining quality
    """
    
    def __init__(self):
        
        # Define compression tiers inspired by bash script but optimized for balance
        self.compression_tiers = {
            'conservative': {  # paling ekstrem (gunakan hanya untuk CCTV/arsip kasar)
                'crf': 35,
                'vbv_maxrate': '1200k',  # Tighter control
                'vbv_bufsize': '2400k', 
                'preset': 'faster',
                'audio_bitrate': '64k',
                'description': 'Smaller file, fast processing'
            },
            'conservative-42': {
                'crf': 42,
                'vbv_maxrate': '700k',
                'vbv_bufsize': '1400k',     
                'preset': 'ultrafast',
                'audio_bitrate': '32k',
                'description': 'Ukuran super kecil, artefak terlihat, proses sangat cepat'
            },
            'balanced': {
                'crf': 38,
                'vbv_maxrate': '1000k',
                'vbv_bufsize': '2000k',
                'preset': 'veryfast',  # Almost ultrafast but more efficient
                'audio_bitrate': '48k',
                'description': 'Minimum file size, fastest processing'
            },
            'aggressive': {
                'crf': 35,
                'vbv_maxrate': '1200k',  # Tighter control
                'vbv_bufsize': '2400k', 
                'preset': 'faster',
                'audio_bitrate': '64k',
                'description': 'Smaller file, fast processing'
            },
            'maximum': {
                'crf': 38,
                'vbv_maxrate': '1000k',
                'vbv_bufsize': '2000k',
                'preset': 'veryfast',  # Almost ultrafast but more efficient
                'audio_bitrate': '48k',
                'description': 'Minimum file size, fastest processing'
            },
            'ultrafast_mode': {  # New mode inspired by bash script
                'crf': 33,
                'vbv_maxrate': '2000k',
                'vbv_bufsize': '4000k',
                'preset': 'ultrafast',
                'audio_bitrate': '48k',
                'description': 'Maximum speed, acceptable quality'
            }
        }
        
    
    def analyze_video_for_vbv(self, filepath):
        """Analyze video to determine optimal CRF + VBV settings"""
        
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', filepath
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, 
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            data = json.loads(result.stdout)
            
            # Extract video stream info
            video_stream = None
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    video_stream = stream
                    break
            
            if not video_stream:
                return None
                
            # Get basic info
            width = int(video_stream.get('width', 0))
            height = int(video_stream.get('height', 0))
            duration = float(data.get('format', {}).get('duration', 0))
            file_size = int(data.get('format', {}).get('size', 0))
            current_bitrate = int(data.get('format', {}).get('bit_rate', 0)) / 1000  # kbps
            
            # Parse frame rate
            frame_rate_str = video_stream.get('r_frame_rate', '0/1')
            if '/' in frame_rate_str:
                num, den = map(int, frame_rate_str.split('/'))
                frame_rate = num / den if den != 0 else 25
            else:
                frame_rate = float(frame_rate_str) if frame_rate_str else 25
            
            # Calculate complexity indicators
            pixel_count = width * height
            pixels_per_second = pixel_count * frame_rate
            file_size_mb = file_size / (1024 * 1024)
            
            return {
                'width': width,
                'height': height,
                'duration': duration,
                'frame_rate': frame_rate,
                'current_bitrate': current_bitrate,
                'file_size_mb': file_size_mb,
                'pixel_count': pixel_count,
                'pixels_per_second': pixels_per_second,
                'bitrate_per_pixel': current_bitrate / pixel_count if pixel_count > 0 else 0,
                'codec': video_stream.get('codec_name', 'unknown')
            }
            
        except Exception as e:
            print(f"Error analyzing video: {e}")
            return None
    
    def determine_compression_tier(self, video_info, target_reduction=0.7, speed_priority=False):
        """
        Determine optimal compression tier based on video characteristics
        
        Args:
            video_info: Video analysis results
            target_reduction: Target file size reduction (0.0-1.0)
            speed_priority: If True, prioritize speed over compression efficiency
        
        Returns:
            dict: Compression settings
        """
        
        if not video_info:
            return self.compression_tiers['ultrafast_mode'] if speed_priority else self.compression_tiers['balanced']
        
        current_bitrate = video_info['current_bitrate']
        pixel_count = video_info['pixel_count']
        bitrate_per_pixel = video_info['bitrate_per_pixel']
        file_size_mb = video_info['file_size_mb']
        
        # If speed is priority, use ultrafast mode for large files
        if speed_priority and file_size_mb > 300:
            return self.compression_tiers['ultrafast_mode']
        
        # Decision logic based on multiple factors (same as before but with ultrafast option)
        
        # High bitrate videos (likely uncompressed or lightly compressed)
        if current_bitrate > 5000:
            if speed_priority:
                return self.compression_tiers['ultrafast_mode']
            elif target_reduction > 0.8:
                return self.compression_tiers['maximum']
            elif target_reduction > 0.6:
                return self.compression_tiers['aggressive']
            else:
                return self.compression_tiers['balanced']
        
        # Medium-high bitrate videos
        elif current_bitrate > 2500:
            if speed_priority:
                return self.compression_tiers['ultrafast_mode']
            elif target_reduction > 0.7:
                return self.compression_tiers['aggressive']
            elif target_reduction > 0.5:
                return self.compression_tiers['balanced']
            else:
                return self.compression_tiers['conservative']
        
        # Medium bitrate videos
        elif current_bitrate > 1500:
            if target_reduction > 0.6:
                return self.compression_tiers['balanced']
            elif target_reduction > 0.4:
                return self.compression_tiers['conservative']
            else:
                # Already well compressed, be very conservative
                tier = self.compression_tiers['conservative'].copy()
                tier['crf'] = 27  # More conservative for size control
                return tier
        
        # Low bitrate videos - be very careful
        else:
            if target_reduction > 0.5:
                return self.compression_tiers['conservative']
            else:
                # Very conservative for already compressed content
                tier = self.compression_tiers['conservative'].copy()
                tier['crf'] = 22
                tier['vbv_maxrate'] = '2500k'
                tier['vbv_bufsize'] = '5000k'
                return tier
    
    def adjust_vbv_for_resolution(self, settings, video_info):
        """Fine-tune VBV settings based on resolution"""
        
        adjusted = settings.copy()
        pixel_count = video_info['pixel_count']
        
        # Resolution-based VBV adjustments
        if pixel_count >= 3840 * 2160:  # 4K
            # 4K needs higher bitrates
            multiplier = 2.0
        elif pixel_count >= 1920 * 1080:  # 1080p
            # Standard multiplier
            multiplier = 1.0
        elif pixel_count >= 1280 * 720:   # 720p
            # Slightly lower for 720p
            multiplier = 0.7
        else:  # Lower resolutions
            # Much lower for small resolutions
            multiplier = 0.4
        
        # Apply multiplier to VBV settings
        maxrate_value = int(adjusted['vbv_maxrate'].replace('k', ''))
        bufsize_value = int(adjusted['vbv_bufsize'].replace('k', ''))
        
        adjusted['vbv_maxrate'] = f"{int(maxrate_value * multiplier)}k"
        adjusted['vbv_bufsize'] = f"{int(bufsize_value * multiplier)}k"
        
        return adjusted
    
    def build_ffmpeg_command_with_vbv(self, input_path, output_path, video_info, speed_priority=False):
        """Build optimized FFmpeg command with CRF + VBV, inspired by bash script approach"""
        
        # Determine compression settings with speed priority option
        settings = self.determine_compression_tier(video_info, speed_priority=speed_priority)
        
        # Adjust for resolution
        if video_info:
            settings = self.adjust_vbv_for_resolution(settings, video_info)
        
        # Build command
        cmd = [
            'ffmpeg', '-y'
        ]
        
        # Add format hint for .dav files (DHAV format from DVR/NVR)
        if input_path.lower().endswith('.dav'):
            cmd.extend(['-f', 'dhav'])
        
        cmd.extend(['-i', input_path])
        
        # Video filters - simplified based on bash script approach
        if settings['preset'] == 'ultrafast':
            # Minimal filtering for ultrafast mode
            filters = ['hqdn3d']  # Only light denoising like bash script
        else:
            # No filters for other modes to maximize speed
            filters = []
            
        if filters:
            cmd.extend(['-vf', ','.join(filters)])
        
        # Core x265 settings
        cmd.extend([
            '-c:v', 'libx265',
            '-crf', str(settings['crf']),
            '-preset', settings['preset'],
            '-maxrate', settings['vbv_maxrate'],
            '-bufsize', settings['vbv_bufsize']
        ])
        
        # x265 parameters based on preset and bash script inspiration
        if settings['preset'] == 'ultrafast':
            # Ultrafast mode inspired by bash script
            x265_params = [
                'no-sao=1',          # Disable SAO for max speed
                'subme=1',           # Minimal subpixel estimation
                'me=dia',            # Fastest motion estimation
                'rd=1',              # Minimal RD optimization
                'vbv-maxrate=' + settings['vbv_maxrate'].replace('k', ''),
                'vbv-bufsize=' + settings['vbv_bufsize'].replace('k', ''),
                'no-weightb=1',      # Disable weighted B-frames
                'no-weightp=1',      # Disable weighted P-frames
                'rc-lookahead=5',    # Minimal lookahead
                'bframes=2',         # Minimal B-frames
                'b-adapt=0',         # Disable adaptive B-frames
                'scenecut=0'         # Disable scene cut detection
            ]
            
            # Add zerolatency-like optimizations
            cmd.extend(['-tune', 'zerolatency'])
            
        else:
            # Balanced parameters for other presets (size-controlled)
            x265_params = [
                'no-sao=0',          # Keep SAO for better compression
                'rd=2',              # Better RD optimization
                'subme=2',           # Better subpixel
                'me=hex',            # Good motion estimation
                'ref=2',             # Keep reference frames
                'rc-lookahead=10',   # Balanced lookahead
                'aq-mode=1',         # Enable AQ
                'aq-strength=0.8',   # Moderate AQ
                'weightp=1',         # Keep weighted P-frames
                'cutree=1',          # Keep cutree
                'bframes=3',         # More B-frames for compression
                'b-adapt=1',         # Adaptive B-frames
                'scenecut=40',       # Scene cut detection
                'psy-rd=1.0',        # Psychovisual optimization
                'deblock=1,1'        # Deblocking
            ]
        
        cmd.extend(['-x265-params', ':'.join(x265_params)])
        
        # Audio encoding - match bash script for ultrafast
        cmd.extend([
            '-c:a', 'aac',
            '-b:a', settings['audio_bitrate'],
            '-ac', '2'  # Force stereo
        ])
        
        # Additional optimizations
        cmd.extend([
            '-threads', '0',     # Use all available threads
            '-progress', 'pipe:1',
            '-nostats',
            '-hide_banner',
            '-loglevel', 'warning',
            output_path
        ])
        
        return cmd, settings
    
    def get_compression_preview(self, video_info, settings):
        """Estimate compression results"""
        
        if not video_info or not settings:
            return "Unable to provide preview"
        
        current_bitrate = video_info['current_bitrate']
        current_size_mb = video_info['file_size_mb']
        duration = video_info['duration']
        
        # Estimate target bitrate (VBV maxrate is the ceiling)
        vbv_maxrate = int(settings['vbv_maxrate'].replace('k', ''))
        
        # Rough estimation: CRF will typically produce bitrate lower than VBV max
        crf = settings['crf']
        if crf <= 30:
            crf_efficiency = 0.8  # CRF allows higher bitrates
        elif crf <= 35:
            crf_efficiency = 0.6  # Moderate compression
        elif crf <= 40:
            crf_efficiency = 0.4  # Aggressive compression
        else:
            crf_efficiency = 0.3  # Very aggressive
        
        # Estimated target bitrate (combination of CRF efficiency and VBV cap)
        estimated_bitrate = min(vbv_maxrate, current_bitrate * crf_efficiency)
        
        # Size estimation
        if duration > 0:
            estimated_size_mb = (estimated_bitrate * duration) / (8 * 1024)  # Convert to MB
            size_reduction = max(0, (current_size_mb - estimated_size_mb) / current_size_mb)
            
            return {
                'current_size_mb': current_size_mb,
                'estimated_size_mb': estimated_size_mb,
                'size_reduction_percent': size_reduction * 100,
                'estimated_bitrate': estimated_bitrate,
                'current_bitrate': current_bitrate,
                'settings': settings,
                'compression_tier': self._get_tier_name(settings)
            }
        
        return "Unable to estimate compression"
    
    def _get_tier_name(self, settings):
        """Get tier name from settings"""
        for name, tier_settings in self.compression_tiers.items():
            if tier_settings['crf'] == settings['crf']:
                return name
        return 'custom'

class VideoCompressorApp(ctk.CTk):
    """
    A modern desktop GUI for batch compressing video files using ffmpeg.
    Enhanced with CRF + VBV compression logic and auto-scan functionality.
    """
    def __init__(self):
        super().__init__()

        # --- Style Colors ---
        self.BLACK = "#000000"
        self.ORANGE = "#00E676" # User's Green Color
        self.WHITE = "#FFFFFF"
        self.GRAY = "#888888"
        self.DARK_GRAY = "#1A1A1A"

        # --- Window Setup ---
        self.title("Video Optimization Dashboard - Auto-Scan & Auto-Delete Enabled")
        self.geometry("1400x800")
        self.minsize(1200, 700)
        self.configure(fg_color=self.BLACK)

        # --- Appearance ---
        ctk.set_appearance_mode("dark")

        # --- State Variables ---
        self.processing_thread = None
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()
        self.entries = {}
        self.start_time = 0
        self.timer_id = None
        self.file_start_time = 0

        # === CPU LIMIT: keep system CPU <= 85% ===
        self.cpu_limit_percent = 85

        # --- Add CRF+VBV Compressor ---
        self.crf_vbv_compressor = CRFWithVBVCompressor()

        # --- CHANGED: Auto-scan and auto-delete are now enabled by default ---
        self.auto_scan_mode = True
        self.auto_delete_mode = True

        # --- Cache for scanned files ---
        self.scanned_files_cache = set()  # Store paths of files already checked
        self.processed_files_cache = set()  # Store paths of successfully processed files
        self.last_full_scan_time = 0
        self.full_scan_interval = 600  # Full rescan every 10 minutes
        self.folder_last_scan = {}  # Track when each folder was last scanned
        
        # --- Round-robin state tracking ---
        self.last_processed_camera = None  # Track last camera processed
        self.camera_order = []  # Maintain consistent camera order

        # --- UI Layout ---
        self.create_widgets()
        self.process_log_queue()
        
        # --- Start System Monitor ---
        psutil.cpu_percent()
        self.update_system_monitor()

    def create_widgets(self):
        """Creates and places all the widgets in the window."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- Header ---
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=40, pady=20, sticky="ew")
        
        ctk.CTkLabel(header_frame, text="Video Optimization Dashboard", font=ctk.CTkFont(family="Power Grotesk", size=28, weight="bold"), text_color=self.ORANGE).pack()
        ctk.CTkLabel(header_frame, text="Auto-Scan & Auto-Delete Enabled by Default v2.4", font=ctk.CTkFont(family="Power Grotesk", size=14), text_color=self.GRAY).pack()

        # --- Configuration Section ---
        config_frame = ctk.CTkFrame(self, fg_color="transparent")
        config_frame.grid(row=1, column=0, padx=40, pady=10, sticky="ew")
        config_frame.grid_columnconfigure((0, 1, 2), weight=1)

        # Directories
        dir_frame = ctk.CTkFrame(config_frame, corner_radius=16, fg_color=self.DARK_GRAY, border_color=self.ORANGE, border_width=1)
        dir_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        dir_frame.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(dir_frame, text="Directories", font=ctk.CTkFont(family="Power Grotesk", size=14, weight="bold"), text_color=self.ORANGE).grid(row=0, column=0, padx=20, pady=(15,10), sticky="w")
        
        dirs_config = [
            ("source", "Source (NAS)", "/Volumes/DSS"),
            ("dest", "Destination (NAS)", "/Volumes/DSS/outrun"),
            ("local", "Local Temp Folder", "/Users/xmacmini/Downloads/temp")
        ]
        for i, (key, label, value) in enumerate(dirs_config):
            ctk.CTkLabel(dir_frame, text=label, text_color=self.GRAY, font=ctk.CTkFont(family="Power Grotesk")).grid(row=i*2+1, column=0, padx=20, pady=(15, 2), sticky="w")
            entry = ctk.CTkEntry(dir_frame, height=40, corner_radius=8, fg_color=self.BLACK, text_color=self.ORANGE, border_width=0, font=ctk.CTkFont(family="Power Grotesk"))
            entry.insert(0, value)
            entry.grid(row=i*2+2, column=0, padx=20, pady=(0, 15), sticky="ew")
            self.entries[key] = entry

        # Current File Status
        info_frame = ctk.CTkFrame(config_frame, corner_radius=16, fg_color=self.DARK_GRAY, border_color=self.ORANGE, border_width=1)
        info_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 10))
        info_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(info_frame, text="Current File Status", font=ctk.CTkFont(family="Power Grotesk", size=14, weight="bold"), text_color=self.ORANGE).grid(row=0, column=0, padx=20, pady=(15,10), sticky="w")
        
        self.input_size_label = ctk.CTkLabel(info_frame, text="--- MB", font=ctk.CTkFont(family="Power Grotesk", size=24, weight="bold"), text_color=self.ORANGE)
        self.input_size_label.grid(row=1, column=0, padx=20, pady=5, sticky="w")
        ctk.CTkLabel(info_frame, text="Input Size", text_color=self.GRAY, font=ctk.CTkFont(family="Power Grotesk")).grid(row=2, column=0, padx=20, sticky="w")
        
        self.output_size_label = ctk.CTkLabel(info_frame, text="--- MB", font=ctk.CTkFont(family="Power Grotesk", size=24, weight="bold"), text_color=self.ORANGE)
        self.output_size_label.grid(row=3, column=0, padx=20, pady=(15, 5), sticky="w")
        ctk.CTkLabel(info_frame, text="Current Output Size", text_color=self.GRAY, font=ctk.CTkFont(family="Power Grotesk")).grid(row=4, column=0, padx=20, sticky="w")

        self.eta_label = ctk.CTkLabel(info_frame, text="--:--", font=ctk.CTkFont(family="Power Grotesk", size=24, weight="bold"), text_color=self.ORANGE)
        self.eta_label.grid(row=5, column=0, padx=20, pady=(15, 5), sticky="w")
        ctk.CTkLabel(info_frame, text="Est. Time Remaining", text_color=self.GRAY, font=ctk.CTkFont(family="Power Grotesk")).grid(row=6, column=0, padx=20, pady=(0, 15), sticky="w")

        # Performance Dashboard
        perf_frame = ctk.CTkFrame(config_frame, corner_radius=16, fg_color=self.DARK_GRAY, border_color=self.ORANGE, border_width=1)
        perf_frame.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
        perf_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(perf_frame, text="Performance Dashboard", font=ctk.CTkFont(family="Power Grotesk", size=14, weight="bold"), text_color=self.ORANGE).grid(row=0, column=0, padx=20, pady=(15,10), sticky="w")
        
        self.time_label = ctk.CTkLabel(perf_frame, text="00:00:00", font=ctk.CTkFont(family="Power Grotesk", size=24, weight="bold"), text_color=self.ORANGE)
        self.time_label.grid(row=1, column=0, padx=20, pady=5, sticky="w")
        ctk.CTkLabel(perf_frame, text="Total Time Elapsed", text_color=self.GRAY, font=ctk.CTkFont(family="Power Grotesk")).grid(row=2, column=0, padx=20, sticky="w")
        
        self.files_processed_label = ctk.CTkLabel(perf_frame, text="0", font=ctk.CTkFont(family="Power Grotesk", size=24, weight="bold"), text_color=self.ORANGE)
        self.files_processed_label.grid(row=3, column=0, padx=20, pady=(15, 5), sticky="w")
        ctk.CTkLabel(perf_frame, text="Files Processed", text_color=self.GRAY, font=ctk.CTkFont(family="Power Grotesk")).grid(row=4, column=0, padx=20, sticky="w")

        self.space_saved_label = ctk.CTkLabel(perf_frame, text="0.00 GB", font=ctk.CTkFont(family="Power Grotesk", size=24, weight="bold"), text_color=self.ORANGE)
        self.space_saved_label.grid(row=5, column=0, padx=20, pady=(15, 5), sticky="w")
        ctk.CTkLabel(perf_frame, text="Total Space Saved", text_color=self.GRAY, font=ctk.CTkFont(family="Power Grotesk")).grid(row=6, column=0, padx=20, pady=(0, 15), sticky="w")

        # --- Progress, Logs, and Controls ---
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.grid(row=2, column=0, padx=38, pady=5, sticky="nsew")
        bottom_frame.grid_rowconfigure(0, weight=1)
        bottom_frame.grid_columnconfigure(0, weight=1)

        # Log and System Monitor Frame
        log_sys_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        log_sys_frame.grid(row=0, column=0, sticky="nsew")
        log_sys_frame.grid_columnconfigure(0, weight=3)
        log_sys_frame.grid_columnconfigure(1, weight=1)
        log_sys_frame.grid_rowconfigure(0, weight=1)

        # Log Area
        self.log_area = ctk.CTkTextbox(log_sys_frame, corner_radius=16, font=("Power Grotesk", 13), fg_color=self.DARK_GRAY, text_color=self.WHITE, border_color=self.ORANGE, border_width=1)
        self.log_area.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.log_area.configure(state='disabled')

        # System Monitor
        sys_frame = ctk.CTkFrame(log_sys_frame, corner_radius=16, fg_color=self.DARK_GRAY, border_color=self.ORANGE, border_width=1)
        sys_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        sys_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(sys_frame, text="System Monitor", font=ctk.CTkFont(family="Power Grotesk", size=14, weight="bold"), text_color=self.ORANGE).grid(row=0, column=0, padx=20, pady=(15,10), sticky="w")
        
        self.cpu_label = ctk.CTkLabel(sys_frame, text="-- %", font=ctk.CTkFont(family="Power Grotesk", size=24, weight="bold"), text_color=self.ORANGE)
        self.cpu_label.grid(row=1, column=0, padx=20, pady=5, sticky="w")
        ctk.CTkLabel(sys_frame, text="CPU Usage", text_color=self.GRAY, font=ctk.CTkFont(family="Power Grotesk")).grid(row=2, column=0, padx=20, sticky="w")
        
        self.ram_label = ctk.CTkLabel(sys_frame, text="-- %", font=ctk.CTkFont(family="Power Grotesk", size=24, weight="bold"), text_color=self.ORANGE)
        self.ram_label.grid(row=3, column=0, padx=20, pady=(15, 5), sticky="w")
        ctk.CTkLabel(sys_frame, text="RAM Usage", text_color=self.GRAY, font=ctk.CTkFont(family="Power Grotesk")).grid(row=4, column=0, padx=20, pady=(0,15), sticky="w")
        
        self.disk_label = ctk.CTkLabel(sys_frame, text="-- %", font=ctk.CTkFont(family="Power Grotesk", size=24, weight="bold"), text_color=self.ORANGE)
        self.disk_label.grid(row=5, column=0, padx=20, pady=(15, 5), sticky="w")
        ctk.CTkLabel(sys_frame, text="Disk Usage", text_color=self.GRAY, font=ctk.CTkFont(family="Power Grotesk")).grid(row=6, column=0, padx=20, pady=(0,15), sticky="w")

        # Progress Bars
        progress_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        progress_frame.grid(row=1, column=0, sticky="ew", pady=(15, 55))
        progress_frame.grid_columnconfigure((0, 1), weight=1)

        # Overall Progress
        overall_progress_container = ctk.CTkFrame(progress_frame, fg_color="transparent")
        overall_progress_container.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        overall_progress_container.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(overall_progress_container, text="Overall Progress", font=ctk.CTkFont(family="Power Grotesk")).grid(row=0, column=0, sticky="w")
        self.overall_progress = ctk.CTkProgressBar(overall_progress_container, height=30, corner_radius=5, fg_color=self.DARK_GRAY, progress_color=self.ORANGE)
        self.overall_progress.set(0)
        self.overall_progress.grid(row=1, column=0, sticky="ew")
        self.overall_label = ctk.CTkLabel(overall_progress_container, text="0 / 0 Files", text_color=self.ORANGE, width=60, font=ctk.CTkFont(family="Power Grotesk"))
        self.overall_label.grid(row=1, column=1, padx=(10,0))

        # Current File Progress
        current_progress_container = ctk.CTkFrame(progress_frame, fg_color="transparent")
        current_progress_container.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        current_progress_container.grid_columnconfigure(0, weight=1)
        self.current_label = ctk.CTkLabel(current_progress_container, text="Current File: (idle)", font=ctk.CTkFont(family="Power Grotesk"))
        self.current_label.grid(row=0, column=0, sticky="w")
        self.current_progress = ctk.CTkProgressBar(current_progress_container, height=30, corner_radius=5, fg_color=self.DARK_GRAY, progress_color=self.ORANGE)
        self.current_progress.set(0)
        self.current_progress.grid(row=1, column=0, sticky="ew")
        self.current_progress_label = ctk.CTkLabel(current_progress_container, text="0%", text_color=self.ORANGE, width=60, font=ctk.CTkFont(family="Power Grotesk"))
        self.current_progress_label.grid(row=1, column=1, padx=(10,0))

        # Controls
        control_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        control_frame.grid(row=2, column=0, sticky="e", pady=(15,15))
        
        # CHANGED: Auto-scan mode toggle - now shows current state (enabled by default)
        self.auto_scan_button = ctk.CTkButton(
            control_frame, 
            text="Disable Auto-Scan", 
            command=self.toggle_auto_scan, 
            height=40, 
            corner_radius=8, 
            fg_color=self.ORANGE, 
            text_color=self.BLACK, 
            font=ctk.CTkFont(family="Power Grotesk", weight="bold"), 
            hover_color="#00B359"
        )
        self.auto_scan_button.pack(side="left", padx=(0, 10))
        
        # CHANGED: Auto-delete mode toggle - now shows current state (enabled by default)
        self.auto_delete_button = ctk.CTkButton(
            control_frame, 
            text="Disable Auto-Delete", 
            command=self.toggle_auto_delete, 
            height=40, 
            corner_radius=8, 
            fg_color="#FF4444", 
            text_color=self.WHITE, 
            font=ctk.CTkFont(family="Power Grotesk", weight="bold"), 
            hover_color="#CC3333"
        )
        self.auto_delete_button.pack(side="left", padx=(0, 10))
        
        self.stop_button = ctk.CTkButton(control_frame, text="Stop", command=self.stop_processing, height=40, corner_radius=8, fg_color=self.DARK_GRAY, text_color=self.WHITE, state="disabled", font=ctk.CTkFont(family="Power Grotesk", weight="bold"), hover_color="#333333")
        self.stop_button.pack(side="left", padx=(0, 10))
        
        self.start_button = ctk.CTkButton(control_frame, text="Start Processing", command=self.start_processing, height=40, font=ctk.CTkFont(family="Power Grotesk", weight="bold"), corner_radius=8, fg_color=self.ORANGE, text_color=self.BLACK, hover_color="#00B359")
        self.start_button.pack(side="left")

        # ADDED: Log the default state immediately after UI creation
        self.after(100, self.log_initial_state)

    def log_initial_state(self):
        """Log the initial state of auto-scan and auto-delete modes"""
        self.log("🚀 APPLICATION STARTED 🚀", "SUCCESS")
        self.log("Auto-scan mode: ENABLED by default - Will continuously scan for new files", "SUCCESS")
        self.log("Auto-delete mode: ENABLED by default - Original .dav files will be DELETED after successful compression!", "WARNING")
        self.log("Ready to start processing. Click 'Start Processing' to begin.", "INFO")

    def toggle_auto_scan(self):
        """Toggle auto-scan mode"""
        self.auto_scan_mode = not self.auto_scan_mode
        if self.auto_scan_mode:
            self.auto_scan_button.configure(text="Disable Auto-Scan", fg_color=self.ORANGE, text_color=self.BLACK)
            self.log("Auto-scan mode ENABLED - Will continuously scan for new files", "SUCCESS")
        else:
            self.auto_scan_button.configure(text="Enable Auto-Scan", fg_color=self.DARK_GRAY, text_color=self.WHITE)
            self.log("Auto-scan mode DISABLED - Will process once only", "INFO")

    def toggle_auto_delete(self):
        """Toggle auto-delete mode"""
        self.auto_delete_mode = not self.auto_delete_mode
        if self.auto_delete_mode:
            self.auto_delete_button.configure(text="Disable Auto-Delete", fg_color="#FF4444", text_color=self.WHITE)
            self.log("AUTO-DELETE mode ENABLED - Original .dav files will be DELETED after successful compression!", "WARNING")
        else:
            self.auto_delete_button.configure(text="Enable Auto-Delete", fg_color=self.DARK_GRAY, text_color=self.WHITE)
            self.log("Auto-delete mode DISABLED - Original files will be preserved", "INFO")

    def safe_delete_original_file(self, file_path):
        """Safely delete original .dav file with verification"""
        try:
            if not self.auto_delete_mode:
                return False
                
            # Additional safety checks
            if not file_path.lower().endswith('.dav'):
                self.log(f"Safety check failed: {file_path} is not a .dav file", "ERROR")
                return False
                
            if not os.path.exists(file_path):
                self.log(f"Original file no longer exists: {file_path}", "WARNING")
                return False
            
            # Get file size before deletion for logging
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            
            # Delete the file
            os.remove(file_path)
            
            # Verify deletion
            if os.path.exists(file_path):
                self.log(f"Failed to delete original file: {file_path}", "ERROR")
                return False
            else:
                self.log(f"Original file deleted: {os.path.basename(file_path)} ({file_size_mb:.2f} MB freed)", "SUCCESS")
                return True
                
        except Exception as e:
            self.log(f"Error deleting original file {file_path}: {e}", "ERROR")
            return False

    def log(self, message, level='INFO'):
        self.log_queue.put((message, level))

    def process_log_queue(self):
        try:
            while True:
                message, level = self.log_queue.get_nowait()
                self.log_area.configure(state='normal')
                self.log_area.insert("end", f"[{level}] {message}\n")
                self.log_area.configure(state='disabled')
                self.log_area.see("end")
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_log_queue)

    def update_timer(self):
        if self.stop_event.is_set():
            return
        elapsed_seconds = time.time() - self.start_time
        hours, rem = divmod(elapsed_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        self.time_label.configure(text=f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}")
        self.timer_id = self.after(1000, self.update_timer)

    def update_system_monitor(self):
        """Updates CPU, RAM, and Disk labels."""
        cpu_percent = psutil.cpu_percent()
        ram_percent = psutil.virtual_memory().percent
        self.cpu_label.configure(text=f"{cpu_percent:.1f} %")
        self.ram_label.configure(text=f"{ram_percent:.1f} %")

        disk_percent = psutil.disk_usage('/').percent
        self.disk_label.configure(text=f"{disk_percent:.1f} %")

        self.after(1000, self.update_system_monitor)
     
    def _cpu_throttle_worker(self, process, stop_evt):
        """
        Throttle ffmpeg agar CPU sistem rata-rata <= self.cpu_limit_percent
        """
        try:
            proc = psutil.Process(process.pid)
        except Exception:
            return

        limit = float(self.cpu_limit_percent)
        hysteresis = 10.0
        sample = 0.5
        min_on = 0.6
        min_off = 0.4
        alpha = 0.3

        ema = None
        state = "on"
        last_switch = time.time()

        try: psutil.cpu_percent(None)
        except Exception: pass

        while process.poll() is None and not stop_evt.is_set() and not self.stop_event.is_set():
            sys_pct = psutil.cpu_percent(interval=sample)
            ema = sys_pct if ema is None else (alpha * sys_pct + (1 - alpha) * ema)
            now = time.time()

            if state == "on":
                if ema > limit and (now - last_switch) >= min_on:
                    try: proc.suspend()
                    except Exception: pass
                    state = "off"
                    last_switch = now
            else:
                if ema < (limit - hysteresis) and (now - last_switch) >= min_off:
                    try: proc.resume()
                    except Exception: pass
                    state = "on"
                    last_switch = now

            time.sleep(0.05)

    def start_processing(self):
        # CHANGED: No warning dialog needed since auto-delete is expected to be enabled by default
        # Just log the current state
        if self.auto_delete_mode:
            self.log("⚠️  AUTO-DELETE IS ACTIVE - Original .dav files will be permanently deleted after compression", "WARNING")
        
        self.time_label.configure(text="00:00:00")
        self.files_processed_label.configure(text="0")
        self.space_saved_label.configure(text="0.00 GB")
        self.input_size_label.configure(text="--- MB")
        self.output_size_label.configure(text="--- MB")
        self.eta_label.configure(text="--:--")
        self.log_area.configure(state='normal')
        self.log_area.delete("1.0", "end")
        self.log_area.configure(state='disabled')
        
        config = {
            "source": self.entries['source'].get(), 
            "dest": self.entries['dest'].get(),
            "tmp": self.entries['local'].get()
        }
        if not os.path.isdir(config['source']):
            messagebox.showerror("Error", f"Source directory not found:\n{config['source']}")
            return
        
        self.set_ui_state(processing=True)
        self.stop_event.clear()
        self.start_time = time.time()
        self.update_timer()
        self.processing_thread = threading.Thread(target=self.processing_loop, args=(config,))
        self.processing_thread.daemon = True
        self.processing_thread.start()

    def stop_processing(self):
        self.log("Stop signal sent. Finishing current operation...", "WARNING")
        if self.timer_id:
            self.after_cancel(self.timer_id)
            self.timer_id = None
        self.stop_event.set()
        self.stop_button.configure(state="disabled")

    def set_ui_state(self, processing):
        state = "disabled" if processing else "normal"
        self.entries['source'].configure(state=state)
        self.entries['dest'].configure(state=state)
        self.entries['local'].configure(state=state)
        self.start_button.configure(state=state)
        self.stop_button.configure(state="normal" if processing else "disabled")
        self.auto_scan_button.configure(state="disabled" if processing else "normal")
        self.auto_delete_button.configure(state="disabled" if processing else "normal")
        if not processing:
            if self.timer_id:
                self.after_cancel(self.timer_id)
                self.timer_id = None
            self.current_label.configure(text="Current File: (idle)")
            self.current_progress.set(0)
            self.current_progress_label.configure(text="0%")

    def get_video_info(self, filepath):
        """Enhanced video analysis for CRF+VBV optimization"""
        return self.crf_vbv_compressor.analyze_video_for_vbv(filepath)

    def _organize_files_round_robin(self, file_list, batch_size=3, start_camera=None):
        """
        Organize files in round-robin fashion across camera folders
        Takes batch_size files from each camera alternately for fair processing
        
        Args:
            file_list: List of file paths (sorted)
            batch_size: Number of files to take from each camera per round
            start_camera: Camera to start from (for continuity after scan)
            
        Returns:
            List organized in round-robin order
        """
        # Group files by camera folder
        camera_files = {}
        for filepath in file_list:
            # Extract camera folder (e.g., 192.168.1.112)
            parts = filepath.split('/')
            camera_folder = None
            for part in parts:
                if part.startswith('192.168.1.'):
                    camera_folder = part
                    break
            
            if camera_folder:
                if camera_folder not in camera_files:
                    camera_files[camera_folder] = []
                camera_files[camera_folder].append(filepath)
        
        # Sort cameras for consistent order
        sorted_cameras = sorted(camera_files.keys())
        
        # Update camera order tracking
        self.camera_order = sorted_cameras
        
        # Reorder cameras to start from the next one after last_processed_camera
        if start_camera and start_camera in sorted_cameras:
            start_idx = sorted_cameras.index(start_camera)
            # Start from NEXT camera after the one we just processed
            next_idx = (start_idx + 1) % len(sorted_cameras)
            sorted_cameras = sorted_cameras[next_idx:] + sorted_cameras[:next_idx]
            self.log(f"Round-robin continuing from camera: {sorted_cameras[0]}", "INFO")
        
        # Round-robin: take batch_size from each camera alternately
        round_robin_list = []
        max_iterations = 10000  # Safety limit
        iteration = 0
        
        while any(len(files) > 0 for files in camera_files.values()) and iteration < max_iterations:
            for camera in sorted_cameras:
                if len(camera_files[camera]) > 0:
                    # Take up to batch_size files from this camera
                    batch = camera_files[camera][:batch_size]
                    round_robin_list.extend(batch)
                    camera_files[camera] = camera_files[camera][batch_size:]
            iteration += 1
        
        return round_robin_list
    
    def scan_for_new_files(self, config, force_full_scan=False):
        """
        Hybrid incremental scan for continuous recording scenario
        Returns files organized in round-robin order for fair processing
        """
        current_time = time.time()
        
        # Determine scan strategy
        time_since_full_scan = current_time - self.last_full_scan_time
        should_full_scan = (
            force_full_scan or 
            self.last_full_scan_time == 0 or 
            time_since_full_scan > self.full_scan_interval
        )
        
        if should_full_scan:
            sorted_files = self._full_directory_scan(config, current_time)
        else:
            sorted_files = self._incremental_scan(config, current_time)
        
        # Apply round-robin organization
        if len(sorted_files) > 0:
            # Pass last_processed_camera for continuity
            round_robin_files = self._organize_files_round_robin(
                sorted_files, 
                batch_size=3, 
                start_camera=self.last_processed_camera
            )
            self.log(f"Organized {len(round_robin_files)} files in round-robin order (3 files per camera)", "INFO")
            return round_robin_files
        
        return sorted_files
    
    def _full_directory_scan(self, config, current_time):
        """Perform complete directory scan"""
        self.log("Performing FULL directory scan...", "INFO")
        scan_start_time = time.time()
        
        dav_files = []
        folder_stats = {}  # Track file count per camera folder
        
        for root, dirs, files in os.walk(config['source']):
            dirs.sort()  # Ensure consistent order
            
            # Get camera folder (e.g., 192.168.1.112)
            parts = root.replace(config['source'], '').strip('/').split('/')
            camera_folder = parts[0] if parts and parts[0] else None
            
            for filename in fnmatch.filter(files, '*.dav'):
                input_path = os.path.join(root, filename)
                
                # Track folder statistics
                if camera_folder:
                    folder_stats[camera_folder] = folder_stats.get(camera_folder, 0) + 1
                
                # Skip if already processed
                if input_path in self.processed_files_cache:
                    continue
                
                # Check if output already exists
                relative_path = os.path.relpath(input_path, config['source'])
                base_no_ext = os.path.splitext(relative_path)[0]
                output_nas_path = os.path.join(config['dest'], base_no_ext + '_compressed.mp4')
                
                if not os.path.exists(output_nas_path):
                    dav_files.append(input_path)
        
        # Update cache and timing
        self.scanned_files_cache = set(dav_files)
        self.last_full_scan_time = current_time
        
        # Update per-folder scan time
        for folder in folder_stats.keys():
            self.folder_last_scan[folder] = current_time
        
        scan_duration = time.time() - scan_start_time
        self.log(f"Full scan complete: {len(dav_files)} unprocessed files in {scan_duration:.1f}s", "SUCCESS")
        
        # Log distribution per camera
        if folder_stats:
            self.log("Files per camera:", "INFO")
            for folder, count in sorted(folder_stats.items()):
                self.log(f"  • {folder}: {count} files", "INFO")
        
        return sorted(dav_files)
    
    def _incremental_scan(self, config, current_time):
        """
        Quick incremental scan - only check folders likely to have new files
        Focus on today's date folders and recently modified directories
        """
        self.log("Performing INCREMENTAL scan for new files...", "INFO")
        scan_start_time = time.time()
        
        new_files = []
        today = time.strftime("%Y-%m-%d")
        yesterday = time.strftime("%Y-%m-%d", time.localtime(current_time - 86400))
        
        # Get list of camera folders
        try:
            camera_folders = [d for d in os.listdir(config['source']) 
                            if d.startswith('192.168.1.') and os.path.isdir(os.path.join(config['source'], d))]
            camera_folders.sort()
        except Exception as e:
            self.log(f"Error listing camera folders: {e}", "WARNING")
            return self._full_directory_scan(config, current_time)
        
        files_found = 0
        
        # Quick scan: only check today and yesterday folders in each camera
        for camera_folder in camera_folders:
            camera_path = os.path.join(config['source'], camera_folder)
            
            # Check today and yesterday date folders
            for date_folder in [today, yesterday]:
                date_path = os.path.join(camera_path, date_folder)
                
                if not os.path.isdir(date_path):
                    continue
                
                try:
                    for filename in os.listdir(date_path):
                        if not filename.lower().endswith('.dav'):
                            continue
                        
                        input_path = os.path.join(date_path, filename)
                        
                        # Skip if already processed
                        if input_path in self.processed_files_cache:
                            continue
                        
                        # Skip if already in pending cache
                        if input_path in self.scanned_files_cache:
                            new_files.append(input_path)
                            continue
                        
                        # Check if output exists
                        relative_path = os.path.relpath(input_path, config['source'])
                        base_no_ext = os.path.splitext(relative_path)[0]
                        output_nas_path = os.path.join(config['dest'], base_no_ext + '_compressed.mp4')
                        
                        if not os.path.exists(output_nas_path):
                            new_files.append(input_path)
                            self.scanned_files_cache.add(input_path)
                            files_found += 1
                
                except Exception as e:
                    self.log(f"Error scanning {date_path}: {e}", "WARNING")
        
        scan_duration = time.time() - scan_start_time
        
        if files_found > 0:
            self.log(f"Incremental scan: Found {files_found} NEW files in {scan_duration:.1f}s", "SUCCESS")
        else:
            self.log(f"Incremental scan: No new files found (checked in {scan_duration:.1f}s)", "INFO")
        
        # Return combined list: cached + new found
        all_pending = [f for f in self.scanned_files_cache if f not in self.processed_files_cache]
        return sorted(all_pending)
    
    def mark_file_as_processed(self, file_path):
        """Mark a file as successfully processed"""
        self.processed_files_cache.add(file_path)
        # Remove from pending scan cache
        if file_path in self.scanned_files_cache:
            self.scanned_files_cache.discard(file_path)

    def processing_loop(self, config):
        total_original_size = 0
        total_compressed_size = 0
        files_processed_count = 0

        try:
            self.log(f"Source root: {config['source']}")
            self.log(f"Output root: {config['dest']}")
            self.log("Speed-optimized CRF+VBV compression engine initialized", "SUCCESS")
            
            if self.auto_scan_mode:
                self.log("AUTO-SCAN MODE: Will continuously scan for new files after each completion", "INFO")
            
            if self.auto_delete_mode:
                self.log("AUTO-DELETE MODE: Original .dav files will be deleted after successful compression", "WARNING")

            os.makedirs(config['dest'], exist_ok=True)
            os.makedirs(config['tmp'], exist_ok=True)

            # Main processing loop - runs continuously if auto-scan is enabled
            scan_counter = 0
            files_in_current_batch = 0  # Track files processed in current round
            
            while not self.stop_event.is_set():
                # Determine if we should force full scan
                # Full scan: at start, every 50 files, or every 10 minutes
                time_since_full = time.time() - self.last_full_scan_time
                force_full = (
                    self.last_full_scan_time == 0 or  # First scan
                    scan_counter % 50 == 0 or  # Every 50 scans
                    time_since_full > 600  # Every 10 minutes
                )
                
                # Scan for files to process
                dav_files = self.scan_for_new_files(config, force_full_scan=force_full)
                total_files = len(dav_files)
                scan_counter += 1
                files_in_current_batch = 0  # Reset batch counter
                
                if total_files == 0:
                    if self.auto_scan_mode:
                        self.log("No new files found. Waiting 30 seconds before next scan...", "INFO")
                        # Wait with checking for stop event
                        for _ in range(30):
                            if self.stop_event.is_set():
                                break
                            time.sleep(1)
                        continue
                    else:
                        self.log("No new files found for processing", "INFO")
                        break

                # Calculate round size (3 files × number of cameras)
                num_cameras = len(self.camera_order) if self.camera_order else 5
                round_size = 3 * num_cameras  # Default: 15 files per round
                
                self.log(f"Processing queue: {total_files} files ready (scanning every {round_size} files)")

                for i, input_path in enumerate(dav_files):
                    if self.stop_event.is_set():
                        self.log("Processing stopped by user.", "WARNING")
                        break

                    # Increment batch counter for EVERY file processed (including skips/corrupts)
                    files_in_current_batch += 1

                    self.overall_progress.set(i / total_files if total_files > 0 else 0)
                    self.overall_label.configure(text=f"{i} / {total_files} Files")
                    self.current_progress.set(0)
                    self.current_progress_label.configure(text="0%")
                    self.output_size_label.configure(text="--- MB")
                    self.eta_label.configure(text="--:--")

                    # Create output path based on relative path from root
                    relative_path = os.path.relpath(input_path, config['source'])
                    base_no_ext = os.path.splitext(relative_path)[0]
                    output_nas_path = os.path.join(config['dest'], base_no_ext + '_compressed.mp4')
                    output_local_path = os.path.join(config['tmp'], os.path.basename(output_nas_path))

                    self.log(f"--- Processing ({i + 1}/{total_files}): {relative_path} ---")
                    self.current_label.configure(text=f"Current File: {relative_path}")
                    
                    # Track camera for this file (do this early for all files)
                    parts = relative_path.split('/')
                    for part in parts:
                        if part.startswith('192.168.1.'):
                            self.last_processed_camera = part
                            break

                    # Double-check if output exists (in case it was created by another process)
                    if os.path.exists(output_nas_path):
                        self.log(f"Skipping: {relative_path} (already exists)", "INFO")
                        self.mark_file_as_processed(input_path)
                        
                        # Check if round complete after skip
                        if self.auto_scan_mode and files_in_current_batch >= round_size:
                            self.log(f"Round complete ({files_in_current_batch} files). Quick scanning for new files...", "INFO")
                            break
                        
                        continue

                    # Ensure output directory exists
                    os.makedirs(os.path.dirname(output_nas_path), exist_ok=True)

                    # Get input file size
                    input_size_bytes = os.path.getsize(input_path)
                    input_size_mb = input_size_bytes / (1024 * 1024)
                    self.input_size_label.configure(text=f"{input_size_mb:.2f} MB")

                    # Analyze video for CRF+VBV optimization
                    video_info = self.get_video_info(input_path)
                    if video_info:
                        self.log(f"Resolution: {video_info['width']}x{video_info['height']}")
                        self.log(f"Bitrate: {video_info['current_bitrate']:.0f} kbps | FPS: {video_info['frame_rate']:.2f}")
                        self.log(f"Duration: {video_info['duration']:.2f}s | Size: {video_info['file_size_mb']:.2f} MB")
                        duration = video_info['duration']
                    else:
                        self.log("Video analysis failed. Using fallback settings.", "WARNING")
                        duration = 0

                    self.file_start_time = time.time()

                    try:
                        # Compress
                        self.run_ffmpeg(input_path, output_local_path, 0, duration)

                        # Get output size
                        output_size_bytes = os.path.getsize(output_local_path)
                        output_size_mb = output_size_bytes / (1024 * 1024)

                        # Update statistics
                        files_processed_count += 1
                        total_original_size += input_size_bytes
                        total_compressed_size += output_size_bytes
                        space_saved_gb = (total_original_size - total_compressed_size) / (1024**3)
                        self.files_processed_label.configure(text=str(files_processed_count))
                        self.space_saved_label.configure(text=f"{space_saved_gb:.2f} GB")

                        # Copy to NAS
                        try:
                            shutil.copy2(output_local_path, output_nas_path)
                            if os.path.exists(output_nas_path) and os.path.getsize(output_nas_path) == output_size_bytes:
                                self.log("Saved to NAS successfully", "SUCCESS")
                                os.remove(output_local_path)
                                
                                # Mark as processed in cache
                                self.mark_file_as_processed(input_path)
                                
                                # AUTO-DELETE: Delete original .dav file if enabled
                                if self.auto_delete_mode:
                                    delete_success = self.safe_delete_original_file(input_path)
                                    if delete_success:
                                        self.log(f"Space freed on NAS: {input_size_mb:.2f} MB", "SUCCESS")
                                    else:
                                        self.log("Failed to delete original file - check logs above", "WARNING")
                                
                                # ===== TRIGGER SCAN AFTER ROUND COMPLETE =====
                                if self.auto_scan_mode and files_in_current_batch >= round_size:
                                    self.log(f"Round complete ({files_in_current_batch} files). Quick scanning for new files...", "INFO")
                                    # Break out of current loop to trigger new scan
                                    break
                                    
                            else:
                                raise Exception("Verification failed after copy")
                        except Exception as e:
                            self.log(f"NAS copy failed: {e}", "ERROR")
                            self.log(f"File left in temp: {output_local_path}", "WARNING")
                            # Don't delete original if copy failed
                            if self.auto_delete_mode:
                                self.log("Original file preserved due to copy failure", "WARNING")

                        # Log compression ratio
                        ratio = ((input_size_mb - output_size_mb) / input_size_mb) * 100
                        self.log(f"Compressed: {input_size_mb:.2f}MB -> {output_size_mb:.2f}MB ({ratio:.1f}% saved)")

                    except Exception as e:
                        error_msg = str(e)
                        self.log(f"Compression failed: {error_msg}", "ERROR")
                        
                        # Clean up failed output
                        if os.path.exists(output_local_path):
                            os.remove(output_local_path)
                        
                        # Check if error is due to corrupt/unreadable file
                        if "could not find codec parameters" in error_msg or "Format dhav detected only with low score" in error_msg:
                            self.log(f"File appears corrupt or unsupported format: {os.path.basename(input_path)}", "WARNING")
                            self.log("Skipping this file and continuing with next...", "INFO")
                            # Mark as "processed" to avoid retry
                            self.mark_file_as_processed(input_path)
                        
                        # Don't delete original if compression failed
                        if self.auto_delete_mode:
                            self.log("Original file preserved due to compression failure", "WARNING")
                        
                        # Check if round complete even after error
                        if self.auto_scan_mode and files_in_current_batch >= round_size:
                            self.log(f"Round complete ({files_in_current_batch} files). Quick scanning for new files...", "INFO")
                            break
                        
                        # Continue to next file instead of stopping
                        continue

                # Update progress for completed batch
                if not self.stop_event.is_set() and total_files > 0:
                    self.overall_progress.set(1)
                    self.overall_label.configure(text=f"{total_files} / {total_files} Files")

                # Exit loop if not in auto-scan mode
                if not self.auto_scan_mode:
                    break

            self.log("--- Processing Complete ---", "SUCCESS")

        except Exception as e:
            self.log(f"Fatal error in processing loop: {e}", "ERROR")
        finally:
            self.set_ui_state(processing=False)

    def run_ffmpeg(self, input_f, output_f, crf_value, duration):
        """Enhanced FFmpeg with CRF+VBV"""
        
        # Get video analysis
        video_info = self.get_video_info(input_f)
        
        if video_info:
            # Build optimized command with CRF+VBV
            args, settings = self.crf_vbv_compressor.build_ffmpeg_command_with_vbv(
                input_f, output_f, video_info
            )
            
            # Log the settings
            tier_name = self.crf_vbv_compressor._get_tier_name(settings)
            self.log(f"Using SIZE-CONTROLLED {tier_name} compression: CRF {settings['crf']}, VBV max {settings['vbv_maxrate']}")
            
            # Show compression preview
            preview = self.crf_vbv_compressor.get_compression_preview(video_info, settings)
            if isinstance(preview, dict):
                self.log(f"Expected size reduction: {preview['size_reduction_percent']:.1f}% (SIZE-OPTIMIZED)")
                
        else:
            # Fallback to safe CRF+VBV settings with DHAV support
            self.log("Using fallback SIZE-CONTROLLED CRF+VBV settings", "WARNING")
            args = [
                'ffmpeg', '-y'
            ]
            
            # Add format hint for .dav files
            if input_f.lower().endswith('.dav'):
                args.extend(['-f', 'dhav'])
            
            args.extend([
                '-i', input_f,
                '-c:v', 'libx265',
                '-crf', '33',
                '-preset', 'fast',
                '-maxrate', '1500k',
                '-bufsize', '3000k',
                '-x265-params', 'rd=2:subme=2:me=hex:ref=2:rc-lookahead=10:aq-mode=1:weightp=1:cutree=1',
                '-c:a', 'aac', '-b:a', '96k', '-ac', '2',
                '-threads', '0',
                '-progress', 'pipe:1', '-nostats', '-hide_banner', '-loglevel', 'warning',
                output_f
            ])
        
        # Execute FFmpeg with progress tracking and timeout protection
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                 universal_newlines=True, creationflags=creation_flags)

        # CPU LIMITER
        throttle_stop_evt = threading.Event()
        throttle_thread = threading.Thread(
            target=self._cpu_throttle_worker,
            args=(process, throttle_stop_evt),
            daemon=True
        )
        throttle_thread.start()
        
        # Track last progress update time to detect stuck processing
        last_progress_time = time.time()
        stuck_timeout = 60  # If no progress for 60 seconds, consider it stuck
        
        for line in process.stdout:
            if self.stop_event.is_set():
                process.kill()
                raise Exception("Process stopped by user.")
            
            # Check if process is stuck (no progress updates)
            current_time = time.time()
            if current_time - last_progress_time > stuck_timeout:
                self.log(f"Process appears stuck (no progress for {stuck_timeout}s), terminating...", "ERROR")
                process.kill()
                raise Exception("Process stuck - no progress updates")
            
            parts = line.strip().split('=')
            if len(parts) == 2:
                key, value = parts
                if key == 'out_time_ms' and duration > 0:
                    try:
                        time_ms = int(value)
                        percent = min(100, int((time_ms / (duration * 1000000)) * 100))
                        self.current_progress.set(percent / 100)
                        self.current_progress_label.configure(text=f"{percent}%")
                        
                        # Update last progress time
                        last_progress_time = current_time
                        
                        if percent > 2:
                            elapsed = time.time() - self.file_start_time
                            total_time = (elapsed * 100) / percent
                            remaining = total_time - elapsed
                            mins, secs = divmod(remaining, 60)
                            self.eta_label.configure(text=f"{int(mins):02}:{int(secs):02}")
                    except (ValueError, ZeroDivisionError):
                        continue
                        
                elif key == 'total_size':
                    if value != "N/A" and value.isdigit():
                        try:
                            size_mb = int(value) / (1024 * 1024)
                            self.output_size_label.configure(text=f"{size_mb:.2f} MB")
                            # Update last progress time
                            last_progress_time = current_time
                        except (ValueError, ZeroDivisionError):
                            continue
        
        process.wait()

        # CPU LIMITER cleanup
        try:
            throttle_stop_evt.set()
            try:
                if process.poll() is None:
                    psutil.Process(process.pid).resume()
            except Exception:
                pass
            if throttle_thread.is_alive():
                throttle_thread.join(timeout=0.5)
        except Exception:
            pass

        if process.returncode != 0:
            stderr_output = process.stderr.read()
            raise Exception(f"ffmpeg exited with code {process.returncode}\n{stderr_output}")


if __name__ == "__main__":
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        subprocess.run(['ffprobe', '-version'], capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    except (subprocess.CalledProcessError, FileNotFoundError):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Dependency Error", "ffmpeg and ffprobe are not found.\nPlease make sure they are installed and accessible in your system's PATH.")
        sys.exit(1)

    app = VideoCompressorApp()
    app.mainloop()
