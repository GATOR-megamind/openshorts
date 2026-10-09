# Running OpenShorts on Windows

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (WSL 2 backend) and [Git](https://git-scm.com/download/win). With an NVIDIA card, keep the GPU driver up to date; Docker Desktop passes the card through on its own.
2. `git clone` this repository.
3. Double-click `windows\OpenShorts.bat`. The first run builds the images, which takes a while. After that it opens the dashboard in its own window at http://localhost:5175.
4. In the dashboard, open **Settings** and paste your keys: Gemini (required) and Upload-Post (for posting).
5. Optional: run `powershell -ExecutionPolicy Bypass -File windows\Create-Desktop-Shortcut.ps1` to get an **OpenShorts** icon on the desktop.

- `OpenShorts.bat update` rebuilds the images after a `git pull`.
- `Stop-OpenShorts.bat` stops the containers. Your clips stay in `output\`.
- When `nvidia-smi` works, the launcher adds `docker-compose.gpu.yml`: CUDA transcription, NVENC encoding, and one job at a time (sized for an 8 GB card).
- From a phone on the same Wi-Fi, open `http://<the PC's local IP>:5175`. Windows asks once whether to allow Docker through the firewall.
