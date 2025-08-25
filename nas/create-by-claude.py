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

class CRFWithVBVCompressor:
    """
    Optimized video compression using CRF with VBV constraints
    Based on Gemini's suggestion for balanced speed and size control
    """
    
    def __init__(self):
        # Define compression tiers with CRF + VBV settings
        self.compression_tiers = {
            'conservative': {
                'crf': 32,
                'vbv_maxrate': '2000k',
                'vbv_bufsize': '4000k',
                'preset': 'medium',
                'audio_bitrate': '128k',
                'description': 'High quality, larger file size'
            },
            'balanced': {
                'crf': 35,
                'vbv_maxrate': '1500k', 
                'vbv_bufsize': '3000k',
                'preset': 'medium',
                'audio_bitrate': '96k',
                'description': 'Good quality, moderate compression'
            },
            'aggressive': {
                'crf': 38,
                'vbv_maxrate': '1000k',
                'vbv_bufsize': '2000k', 
                'preset': 'fast',
                'audio_bitrate': '64k',
                'description': 'Smaller file, acceptable quality'
            },
            'maximum': {
                'crf': 42,
                'vbv_maxrate': '800k',
                'vbv_bufsize': '1600k',
                'preset': 'faster',
                'audio_bitrate': '48k',
                'description': 'Minimum file size, lower quality'
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
    
    def determine_compression_tier(self, video_info, target_reduction=0.7):
        """
        Determine optimal compression tier based on video characteristics
        
        Args:
            video_info: Video analysis results
            target_reduction: Target file size reduction (0.0-1.0)
        
        Returns:
            dict: Compression settings
        """
        
        if not video_info:
            return self.compression_tiers['balanced']
        
        current_bitrate = video_info['current_bitrate']
        pixel_count = video_info['pixel_count']
        bitrate_per_pixel = video_info['bitrate_per_pixel']
        file_size_mb = video_info['file_size_mb']
        
        # Decision logic based on multiple factors
        
        # High bitrate videos (likely uncompressed or lightly compressed)
        if current_bitrate > 5000:
            if target_reduction > 0.8:
                return self.compression_tiers['maximum']
            elif target_reduction > 0.6:
                return self.compression_tiers['aggressive']
            else:
                return self.compression_tiers['balanced']
        
        # Medium-high bitrate videos
        elif current_bitrate > 2500:
            if target_reduction > 0.7:
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
                tier['crf'] = 28  # Even more conservative
                return tier
        
        # Low bitrate videos - be very careful
        else:
            if target_reduction > 0.5:
                return self.compression_tiers['conservative']
            else:
                # Very conservative for already compressed content
                tier = self.compression_tiers['conservative'].copy()
                tier['crf'] = 25
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
    
    def build_ffmpeg_command_with_vbv(self, input_path, output_path, video_info):
        """Build optimized FFmpeg command with CRF + VBV"""
        
        # Determine compression settings
        settings = self.determine_compression_tier(video_info)
        
        # Adjust for resolution
        if video_info:
            settings = self.adjust_vbv_for_resolution(settings, video_info)
        
        # Build command
        cmd = [
            'ffmpeg', '-y', '-i', input_path
        ]
        
        # Video filters - keep it simple for speed
        filters = ['hqdn3d=2:1:2:1']  # Light denoising
        cmd.extend(['-vf', ','.join(filters)])
        
        # Core x265 settings with CRF + VBV
        cmd.extend([
            '-c:v', 'libx265',
            '-crf', str(settings['crf']),
            '-preset', settings['preset'],
            '-maxrate', settings['vbv_maxrate'],
            '-bufsize', settings['vbv_bufsize']
        ])
        
        # Optimized x265 parameters for speed and quality balance
        x265_params = [
            'no-sao=0',  # Keep SAO for quality
            'rd=2',      # Balanced RD optimization  
            'subme=2',   # Balanced subpixel estimation
            'me=hex',    # Good motion estimation
            'ref=2',     # Reasonable reference frames
            'rc-lookahead=15',  # Reasonable lookahead
            'aq-mode=1', # Adaptive quantization
            'aq-strength=0.8',  # Moderate AQ strength
            'psy-rd=1.0', # Psychovisual optimization
            'deblock=1,1' # Enable deblocking
        ]
        
        cmd.extend(['-x265-params', ':'.join(x265_params)])
        
        # Audio settings
        cmd.extend([
            '-c:a', 'aac',
            '-b:a', settings['audio_bitrate']
        ])
        
        # Progress and output
        cmd.extend([
            '-progress', 'pipe:1',
            '-nostats',
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
    Enhanced with CRF + VBV compression logic.
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
        self.title("Video Compression Dashboard")
        self.geometry("1400x800") # Wider for the new panel
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

        # --- Add CRF+VBV Compressor ---
        self.crf_vbv_compressor = CRFWithVBVCompressor()

        # --- UI Layout ---
        self.create_widgets()
        self.process_log_queue()
        
        # --- Start System Monitor ---
        psutil.cpu_percent() # Initial call to get a baseline
        self.update_system_monitor()

    def create_widgets(self):
        """Creates and places all the widgets in the window."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- Header ---
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=40, pady=20, sticky="ew")
        
        ctk.CTkLabel(header_frame, text="Video Compression Dashboard", font=ctk.CTkFont(family="Power Grotesk", size=28, weight="bold"), text_color=self.ORANGE).pack()
        ctk.CTkLabel(header_frame, text="Beta Version 2.0 - CRF+VBV Enhanced", font=ctk.CTkFont(family="Power Grotesk", size=14), text_color=self.GRAY).pack()

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
            ("source", "Source (NAS)", "/Volumes/DSS/recordings"),
            ("dest", "Destination (NAS)", "/Volumes/DSS/compressed"),
            ("local", "Local Temp Folder", "/Users/apple/Downloads/temp")
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

        # System Monitor (Moved)
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

        # Progress Bars in their own frame
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
        
        self.stop_button = ctk.CTkButton(control_frame, text="Stop", command=self.stop_processing, height=40, corner_radius=8, fg_color=self.DARK_GRAY, text_color=self.WHITE, state="disabled", font=ctk.CTkFont(family="Power Grotesk", weight="bold"), hover_color="#333333")
        self.stop_button.pack(side="left", padx=(0, 10))
        
        self.start_button = ctk.CTkButton(control_frame, text="Start Processing", command=self.start_processing, height=40, font=ctk.CTkFont(family="Power Grotesk", weight="bold"), corner_radius=8, fg_color=self.ORANGE, text_color=self.BLACK, hover_color="#00B359")
        self.start_button.pack(side="left")

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

    def start_processing(self):
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
            "source": self.entries['source'].get(), "dest": self.entries['dest'].get(),
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

    def processing_loop(self, config):
        total_original_size = 0
        total_compressed_size = 0
        files_processed_count = 0
        try:
            self.log(f"Source: {config['source']}")
            self.log(f"Output: {config['dest']}")
            self.log("Enhanced CRF+VBV compression engine initialized", "SUCCESS")
            
            os.makedirs(config['dest'], exist_ok=True)
            os.makedirs(config['tmp'], exist_ok=True)
            files = [f for f in os.listdir(config['source']) if f.lower().endswith('.dav')]
            total_files = len(files)
            self.log(f"Found {total_files} .dav files for processing")
            
            for i, filename in enumerate(files):
                if self.stop_event.is_set():
                    self.log("Processing stopped by user.", "WARNING")
                    break
                
                self.overall_progress.set((i) / total_files if total_files > 0 else 0)
                self.overall_label.configure(text=f"{i} / {total_files} Files")
                self.current_progress.set(0)
                self.current_progress_label.configure(text="0%")
                self.output_size_label.configure(text="--- MB")
                self.eta_label.configure(text="--:--")
                
                basename = os.path.splitext(filename)[0]
                input_path = os.path.join(config['source'], filename)
                output_nas_path = os.path.join(config['dest'], f"{basename}_compressed.mp4")
                output_local_path = os.path.join(config['tmp'], f"{basename}_compressed.mp4")
                
                self.log(f"--- Processing ({i + 1}/{total_files}): {basename} ---")
                self.current_label.configure(text=f"Current File: {filename}")
                
                if os.path.exists(output_nas_path):
                    self.log(f"Skipping: {basename} (already exists on NAS)")
                    continue
                
                input_size_bytes = os.path.getsize(input_path)
                input_size_mb = input_size_bytes / (1024 * 1024)
                self.input_size_label.configure(text=f"{input_size_mb:.2f} MB")

                # Enhanced video analysis with CRF+VBV
                video_info = self.get_video_info(input_path)
                
                if video_info:
                    self.log(f"Resolution: {video_info['width']}x{video_info['height']}")
                    self.log(f"Current bitrate: {video_info['current_bitrate']:.0f} kbps")
                    self.log(f"Frame rate: {video_info['frame_rate']:.2f} fps")
                    self.log(f"File size: {video_info['file_size_mb']:.2f} MB")
                    duration = video_info['duration']
                else:
                    self.log("Could not analyze video properties, using fallback settings", "WARNING")
                    duration = 0

                self.file_start_time = time.time()

                try:
                    # Use enhanced CRF+VBV compression
                    self.run_ffmpeg(input_path, output_local_path, 0, duration)  # CRF value ignored now
                    
                    output_size_bytes = os.path.getsize(output_local_path)
                    output_size_mb = output_size_bytes / (1024 * 1024)
                    
                    files_processed_count += 1
                    total_original_size += input_size_bytes
                    total_compressed_size += output_size_bytes
                    space_saved_gb = (total_original_size - total_compressed_size) / (1024**3)

                    self.files_processed_label.configure(text=str(files_processed_count))
                    self.space_saved_label.configure(text=f"{space_saved_gb:.2f} GB")

                    self.log("Copying to NAS...")
                    os.rename(output_local_path, output_nas_path)
                    self.log(f"Successfully saved to NAS", "SUCCESS")
                    
                    compression_ratio = ((input_size_mb - output_size_mb) / input_size_mb) * 100
                    self.log(f"Compression: {compression_ratio:.1f}% ({input_size_mb:.2f}MB -> {output_size_mb:.2f}MB)")

                except Exception as e:
                    self.log(f"Compression failed: {e}", "ERROR")
                    # Clean up failed output file
                    if os.path.exists(output_local_path):
                        os.remove(output_local_path)

            if not self.stop_event.is_set() and total_files > 0:
                self.overall_progress.set(1)
                self.overall_label.configure(text=f"{total_files} / {total_files} Files")
            self.log("--- Processing Complete ---", "SUCCESS")
        except Exception as e:
            self.log(f"An unexpected error occurred: {e}", "ERROR")
        finally:
            self.set_ui_state(processing=False)

    def run_ffmpeg(self, input_f, output_f, crf_value, duration):
        """Enhanced FFmpeg with CRF+VBV - crf_value parameter is now ignored"""
        
        # Get video analysis
        video_info = self.get_video_info(input_f)
        
        if video_info:
            # Build optimized command with CRF+VBV
            args, settings = self.crf_vbv_compressor.build_ffmpeg_command_with_vbv(
                input_f, output_f, video_info
            )
            
            # Log the settings
            tier_name = self.crf_vbv_compressor._get_tier_name(settings)
            self.log(f"Using {tier_name} compression: CRF {settings['crf']}, VBV max {settings['vbv_maxrate']}")
            
            # Show compression preview
            preview = self.crf_vbv_compressor.get_compression_preview(video_info, settings)
            if isinstance(preview, dict):
                self.log(f"Expected size reduction: {preview['size_reduction_percent']:.1f}%")
                
        else:
            # Fallback to safe CRF+VBV settings
            self.log("Using fallback CRF+VBV settings", "WARNING")
            args = [
                'ffmpeg', '-y', '-i', input_f,
                '-vf', 'hqdn3d=2:1:2:1',  # Light denoising
                '-c:v', 'libx265',
                '-crf', '35',             # Moderate CRF
                '-preset', 'medium',      # Balanced preset
                '-maxrate', '1500k',      # VBV cap
                '-bufsize', '3000k',      # VBV buffer
                '-x265-params', 'rd=2:subme=2:me=hex:ref=2:aq-mode=1',
                '-c:a', 'aac', '-b:a', '96k',
                '-progress', 'pipe:1', '-nostats',
                output_f
            ]
        
        # Execute FFmpeg with progress tracking
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                 universal_newlines=True, creationflags=creation_flags)
        
        for line in process.stdout:
            if self.stop_event.is_set():
                process.kill()
                raise Exception("Process stopped by user.")
            
            parts = line.strip().split('=')
            if len(parts) == 2:
                key, value = parts
                if key == 'out_time_ms' and duration > 0:
                    try:
                        time_ms = int(value)
                        percent = min(100, int((time_ms / (duration * 1000000)) * 100))
                        self.current_progress.set(percent / 100)
                        self.current_progress_label.configure(text=f"{percent}%")
                        
                        if percent > 2:
                            elapsed = time.time() - self.file_start_time
                            total_time = (elapsed * 100) / percent
                            remaining = total_time - elapsed
                            mins, secs = divmod(remaining, 60)
                            self.eta_label.configure(text=f"{int(mins):02}:{int(secs):02}")
                    except (ValueError, ZeroDivisionError):
                        # Skip invalid time values
                        continue
                        
                elif key == 'total_size':
                    # Handle the N/A case that was causing the error
                    if value != "N/A" and value.isdigit():
                        try:
                            size_mb = int(value) / (1024 * 1024)
                            self.output_size_label.configure(text=f"{size_mb:.2f} MB")
                        except (ValueError, ZeroDivisionError):
                            # Skip invalid size values
                            continue
        
        process.wait()
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
