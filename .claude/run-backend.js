const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const backendDir = path.join(__dirname, '..', 'backend');
process.chdir(backendDir);

// Prefer the Python 3.9 at CommandLineTools because that's where uvicorn + deps are installed
const pythonCandidates = [
  '/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3',
  path.join(backendDir, '.venv', 'bin', 'python3'),
  path.join(backendDir, 'venv', 'bin', 'python3'),
  '/usr/local/bin/python3',
  '/usr/bin/python3',
];
const python = pythonCandidates.find(p => { try { fs.accessSync(p); return true; } catch { return false; } }) || 'python3';

// Prepend ~/Library/Python/3.9/bin so yt-dlp is on PATH for the extraction service
const userBinPath = path.join(process.env.HOME || '', 'Library', 'Python', '3.9', 'bin');
const PATH = `${userBinPath}:${process.env.PATH || ''}`;

const child = spawn(
  python,
  ['-m', 'uvicorn', 'server:app', '--host', '0.0.0.0', '--port', '8000', '--reload'],
  {
    cwd: backendDir,
    stdio: 'inherit',
    env: { ...process.env, PATH, PYTHONUNBUFFERED: '1' },
  }
);

child.on('exit', code => process.exit(code || 0));
process.on('SIGTERM', () => child.kill('SIGTERM'));
process.on('SIGINT',  () => child.kill('SIGINT'));
