import customtkinter as ctk
from tkinter import messagebox
import subprocess
import threading
import queue
import os
import sys
import time

class VideoCompressorApp(ctk.CTk):
    """
    A modern desktop GUI for batch compressing video files using ffmpeg.
    Styled with a Brutalism-inspired UI, rounded corners, and a yellow accent.
    Includes a performance dashboard.
    """
    def __init__(self):
        super().__init__()

        # --- Style Colors ---
        self.BLACK = "#000000"
        self.YELLOW = "#00E676" # Valentino Rossi Yellow
        self.WHITE = "#FFFFFF"
        self.GRAY = "#AAAAAA"
        self.DARK_GRAY = "#111111"

        # --- Window Setup ---
        self.title("Video Compression Dashboard")
        self.geometry("1100x800") # Wider for performance dashboard
        self.minsize(1000, 700)
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

        # --- UI Layout ---
        self.create_widgets()
        self.process_log_queue()

    def create_widgets(self):
        """Creates and places all the widgets in the window."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- Header ---
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        
        ctk.CTkLabel(header_frame, text="VIDEO COMPRESSION DASHBOARD", font=ctk.CTkFont(family="Monument Extended", size=24, weight="bold"), text_color=self.WHITE).pack()
        ctk.CTkLabel(header_frame, text="Batch compress .dav files to .mp4 using ffmpeg", font=ctk.CTkFont(family="Monument Extended", size=11), text_color=self.GRAY).pack()

        # --- Configuration Section ---
        config_frame = ctk.CTkFrame(self, fg_color="transparent")
        config_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        config_frame.grid_columnconfigure((0, 1, 2), weight=1) # Added a third column

        # Directories
        dir_frame = ctk.CTkFrame(config_frame, corner_radius=8, fg_color=self.YELLOW)
        dir_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        dir_frame.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(dir_frame, text="DIRECTORIES", font=ctk.CTkFont(family="Monument Extended", size=14, weight="bold"), text_color=self.BLACK).grid(row=0, column=0, padx=20, pady=(15,10), sticky="w")
        
        dirs_config = [
            ("source", "Source (NAS)", "/Volumes/DSS/recordings"),
            ("dest", "Destination (NAS)", "/Volumes/DSS/compressed"),
            ("local", "Local Temp Folder", "/Users/apple/Downloads/temp")
        ]
        for i, (key, label, value) in enumerate(dirs_config):
            ctk.CTkLabel(dir_frame, text=label, text_color=self.BLACK, font=ctk.CTkFont(family="Monument Extended")).grid(row=i*2+1, column=0, padx=20, pady=(5, 2), sticky="w")
            entry = ctk.CTkEntry(dir_frame, height=40, corner_radius=8, fg_color=self.BLACK, text_color=self.WHITE, border_width=1, border_color=self.BLACK)
            entry.insert(0, value)
            entry.grid(row=i*2+2, column=0, padx=20, pady=(0, 15), sticky="ew")
            self.entries[key] = entry

        # Target Settings
        target_frame = ctk.CTkFrame(config_frame, corner_radius=8, fg_color=self.YELLOW)
        target_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 10))
        target_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(target_frame, text="COMPRESSION TARGET", font=ctk.CTkFont(family="Monument Extended", size=14, weight="bold"), text_color=self.BLACK).grid(row=0, column=0, padx=20, pady=(15,10), sticky="w")
        
        size_frame = ctk.CTkFrame(target_frame, fg_color="transparent")
        size_frame.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        size_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(size_frame, text="Min Size (MB)", text_color=self.BLACK, font=ctk.CTkFont(family="Monument Extended")).grid(row=0, column=0, sticky="w")
        self.entries['min'] = ctk.CTkEntry(size_frame, height=40, corner_radius=8, fg_color=self.BLACK, text_color=self.WHITE, border_width=1, border_color=self.BLACK)
        self.entries['min'].insert(0, "100")
        self.entries['min'].grid(row=1, column=0, sticky="ew", padx=(0, 5))
        
        ctk.CTkLabel(size_frame, text="Max Size (MB)", text_color=self.BLACK, font=ctk.CTkFont(family="Monument Extended")).grid(row=0, column=1, sticky="w")
        self.entries['max'] = ctk.CTkEntry(size_frame, height=40, corner_radius=8, fg_color=self.BLACK, text_color=self.WHITE, border_width=1, border_color=self.BLACK)
        self.entries['max'].insert(0, "150")
        self.entries['max'].grid(row=1, column=1, sticky="ew", padx=(5,0))
        
        # Performance Dashboard
        perf_frame = ctk.CTkFrame(config_frame, corner_radius=8, fg_color=self.DARK_GRAY, border_color=self.YELLOW, border_width=1)
        perf_frame.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
        perf_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(perf_frame, text="PERFORMANCE DASHBOARD", font=ctk.CTkFont(family="Monument Extended", size=14, weight="bold"), text_color=self.YELLOW).grid(row=0, column=0, padx=20, pady=(15,10), sticky="w")
        
        self.time_label = ctk.CTkLabel(perf_frame, text="00:00:00", font=ctk.CTkFont(family="Monument Extended", size=24, weight="bold"))
        self.time_label.grid(row=1, column=0, padx=20, pady=5, sticky="w")
        ctk.CTkLabel(perf_frame, text="Total Time Elapsed", text_color=self.GRAY, font=ctk.CTkFont(family="Monument Extended")).grid(row=2, column=0, padx=20, sticky="w")
        
        self.files_processed_label = ctk.CTkLabel(perf_frame, text="0", font=ctk.CTkFont(family="Monument Extended", size=24, weight="bold"))
        self.files_processed_label.grid(row=3, column=0, padx=20, pady=(15, 5), sticky="w")
        ctk.CTkLabel(perf_frame, text="Files Processed", text_color=self.GRAY, font=ctk.CTkFont(family="Monument Extended")).grid(row=4, column=0, padx=20, sticky="w")

        self.space_saved_label = ctk.CTkLabel(perf_frame, text="0.00 GB", font=ctk.CTkFont(family="Monument Extended", size=24, weight="bold"))
        self.space_saved_label.grid(row=5, column=0, padx=20, pady=(15, 5), sticky="w")
        ctk.CTkLabel(perf_frame, text="Total Space Saved", text_color=self.GRAY, font=ctk.CTkFont(family="Monument Extended")).grid(row=6, column=0, padx=20, pady=(0, 15), sticky="w")

        # --- Progress, Logs, and Controls ---
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.grid(row=2, column=0, padx=20, pady=20, sticky="nsew")
        bottom_frame.grid_rowconfigure(4, weight=1)
        bottom_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(bottom_frame, text="Overall Progress", font=ctk.CTkFont(family="Monument Extended")).grid(row=0, column=0, sticky="w")
        overall_progress_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        overall_progress_frame.grid(row=1, column=0, sticky="ew")
        overall_progress_frame.grid_columnconfigure(0, weight=1)
        
        self.overall_progress = ctk.CTkProgressBar(overall_progress_frame, height=8, corner_radius=8, fg_color=self.GRAY, progress_color=self.YELLOW)
        self.overall_progress.set(0)
        self.overall_progress.grid(row=0, column=0, sticky="ew")
        
        self.overall_label = ctk.CTkLabel(overall_progress_frame, text="0 / 0 Files", text_color=self.GRAY, width=70, font=ctk.CTkFont(family="Monument Extended"))
        self.overall_label.grid(row=0, column=1, sticky="w", padx=(10,0))

        self.current_label = ctk.CTkLabel(bottom_frame, text="Current File: (idle)", font=ctk.CTkFont(family="Monument Extended"))
        self.current_label.grid(row=2, column=0, sticky="w", pady=(10, 0))
        current_progress_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        current_progress_frame.grid(row=3, column=0, sticky="ew")
        current_progress_frame.grid_columnconfigure(0, weight=1)

        self.current_progress = ctk.CTkProgressBar(current_progress_frame, height=8, corner_radius=8, fg_color=self.GRAY, progress_color=self.YELLOW)
        self.current_progress.set(0)
        self.current_progress.grid(row=0, column=0, sticky="ew")
        
        self.current_progress_label = ctk.CTkLabel(current_progress_frame, text="0%", text_color=self.GRAY, width=40, font=ctk.CTkFont(family="Monument Extended"))
        self.current_progress_label.grid(row=0, column=1, sticky="w", padx=(10,0))

        self.log_area = ctk.CTkTextbox(bottom_frame, corner_radius=8, font=("Monument Extended", 11), fg_color=self.DARK_GRAY, text_color=self.WHITE, border_width=1, border_color=self.YELLOW)
        self.log_area.grid(row=4, column=0, sticky="nsew", pady=15)
        self.log_area.configure(state='disabled')
        bottom_frame.grid_rowconfigure(4, weight=1)

        control_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        control_frame.grid(row=5, column=0, sticky="s")
        
        self.start_button = ctk.CTkButton(control_frame, text="START PROCESSING", command=self.start_processing, height=40, font=ctk.CTkFont(family="Monument Extended", weight="bold"), corner_radius=8, fg_color=self.YELLOW, text_color=self.BLACK, hover_color="#EAB308")
        self.start_button.pack(side="left", padx=(0, 5), pady=(10,0))
        
        self.stop_button = ctk.CTkButton(control_frame, text="STOP", command=self.stop_processing, height=40, corner_radius=8, fg_color=self.GRAY, text_color=self.BLACK, state="disabled", font=ctk.CTkFont(family="Monument Extended", weight="bold"), hover_color="#999999")
        self.stop_button.pack(side="left", padx=(5, 0), pady=(10,0))

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
        """Updates the elapsed time label every second."""
        if self.stop_event.is_set():
            return
        
        elapsed_seconds = time.time() - self.start_time
        hours, rem = divmod(elapsed_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        self.time_label.configure(text=f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}")
        
        self.timer_id = self.after(1000, self.update_timer)

    def start_processing(self):
        # Reset dashboard
        self.time_label.configure(text="00:00:00")
        self.files_processed_label.configure(text="0")
        self.space_saved_label.configure(text="0.00 GB")

        self.log_area.configure(state='normal')
        self.log_area.delete("1.0", "end")
        self.log_area.configure(state='disabled')
        
        config = {
            "source": self.entries['source'].get(), "dest": self.entries['dest'].get(),
            "tmp": self.entries['local'].get(), "min": int(self.entries['min'].get()),
            "max": int(self.entries['max'].get())
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
        for entry in self.entries.values():
            entry.configure(state=state)
        self.start_button.configure(state=state)
        self.stop_button.configure(state="normal" if processing else "disabled")
        if not processing:
            if self.timer_id:
                self.after_cancel(self.timer_id)
                self.timer_id = None
            self.current_label.configure(text="Current File: (idle)")
            self.current_progress.set(0)
            self.current_progress_label.configure(text="0%")

    def processing_loop(self, config):
        total_original_size = 0
        total_compressed_size = 0
        files_processed_count = 0

        try:
            self.log(f"Source: {config['source']}")
            self.log(f"Output: {config['dest']}")
            os.makedirs(config['dest'], exist_ok=True)
            os.makedirs(config['tmp'], exist_ok=True)
            files = [f for f in os.listdir(config['source']) if f.lower().endswith('.dav')]
            total_files = len(files)
            self.log(f"Ditemukan {total_files} file .dav untuk diproses")
            
            for i, filename in enumerate(files):
                if self.stop_event.is_set():
                    self.log("Processing stopped by user.", "WARNING")
                    break
                
                self.overall_progress.set((i) / total_files if total_files > 0 else 0)
                self.overall_label.configure(text=f"{i} / {total_files} Files")
                self.current_progress.set(0)
                self.current_progress_label.configure(text="0%")

                basename = os.path.splitext(filename)[0]
                input_path = os.path.join(config['source'], filename)
                output_nas_path = os.path.join(config['dest'], f"{basename}_compressed.mp4")
                output_local_path = os.path.join(config['tmp'], f"{basename}_compressed.mp4")

                self.log(f"--- Memproses ({i + 1}/{total_files}): {basename} ---")
                self.current_label.configure(text=f"Current File: {filename}")

                if os.path.exists(output_nas_path):
                    self.log(f"Melewati: {basename} (sudah ada di NAS)")
                    continue

                input_size_bytes = os.path.getsize(input_path)
                input_size_mb = input_size_bytes / (1024 * 1024)
                duration = self.get_duration(input_path)
                self.log(f"Input: {input_size_mb:.2f}MB, {duration}s")

                success, final_size = False, -1
                for attempt in range(1, 4):
                    if self.stop_event.is_set(): break
                    vbv_max = 2000 * attempt
                    vbv_buf = vbv_max * 2
                    try:
                        self.run_ffmpeg(input_path, output_local_path, vbv_max, vbv_buf, duration)
                        output_size_bytes = os.path.getsize(output_local_path)
                        output_size_mb = output_size_bytes / (1024 * 1024)
                        self.log(f"Output (Attempt {attempt}): {output_size_mb:.2f}MB", "SUCCESS")
                        if output_size_mb <= config['max']:
                            final_size, success = output_size_mb, True
                            break
                        else:
                            self.log(f"Masih terlalu besar (>{config['max']}MB)", "WARNING")
                            if attempt < 3: os.remove(output_local_path)
                            else: final_size, success = output_size_mb, True
                    except Exception as e:
                        self.log(f"Gagal kompresi (Attempt {attempt}): {e}", "ERROR")
                        break
                
                if success and not self.stop_event.is_set():
                    files_processed_count += 1
                    total_original_size += input_size_bytes
                    total_compressed_size += os.path.getsize(output_local_path)
                    space_saved_gb = (total_original_size - total_compressed_size) / (1024**3)

                    self.files_processed_label.configure(text=str(files_processed_count))
                    self.space_saved_label.configure(text=f"{space_saved_gb:.2f} GB")

                    self.log("Menyalin ke NAS...")
                    os.rename(output_local_path, output_nas_path)
                    self.log(f"Berhasil disimpan ke NAS", "SUCCESS")
                    ratio = 100 - (final_size * 100 / input_size_mb)
                    self.log(f"Penghematan: {ratio:.0f}% ({input_size_mb:.2f}MB -> {final_size:.2f}MB)")

            if not self.stop_event.is_set() and total_files > 0:
                self.overall_progress.set(1)
                self.overall_label.configure(text=f"{total_files} / {total_files} Files")
            
            self.log("--- Proses Selesai ---", "SUCCESS")

        except Exception as e:
            self.log(f"An unexpected error occurred: {e}", "ERROR")
        finally:
            self.set_ui_state(processing=False)

    def get_duration(self, filepath):
        cmd = ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', filepath]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.log("ffprobe not found or failed.", "ERROR")
            return 0

    def run_ffmpeg(self, input_f, output_f, vbv_max, vbv_buf, duration):
        args = [
            'ffmpeg', '-y', '-i', input_f, '-vf', 'hqdn3d', '-vcodec', 'libx265', '-crf', '33',
            '-preset', 'ultrafast', '-tune', 'zerolatency',
            '-x265-params', f"no-sao=1:subme=1:me=dia:rd=1:vbv-maxrate={vbv_max}:vbv-bufsize={vbv_buf}",
            '-c:a', 'aac', '-b:a', '48k', '-progress', 'pipe:1', '-nostats', output_f
        ]
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, creationflags=creation_flags)
        
        for line in process.stdout:
            if self.stop_event.is_set():
                process.kill()
                raise Exception("Process stopped by user.")
            if 'out_time_ms' in line and duration > 0:
                time_ms = int(line.split('=')[1])
                percent = min(100, int((time_ms / (duration * 1000000)) * 100))
                self.current_progress.set(percent / 100)
                self.current_progress_label.configure(text=f"{percent}%")
        
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
