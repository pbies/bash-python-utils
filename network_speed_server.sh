#!/bin/bash

# Network Speed Test Server
# Listens for speed test requests from clients

SERVER_PORT=5201
LOG_FILE="/tmp/speed_test_server.log"

# Function to log messages with timestamp
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Function to handle cleanup
cleanup() {
    log_message "Shutting down speed test server..."
    if [ -n "$iperf_pid" ]; then
        kill $iperf_pid 2>/dev/null
    fi
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Check if iperf3 is installed
if ! command -v iperf3 &> /dev/null; then
    echo "Error: iperf3 is required but not installed."
    echo "Install it with:"
    echo "  Ubuntu/Debian: sudo apt-get install iperf3"
    echo "  CentOS/RHEL: sudo yum install iperf3"
    echo "  macOS: brew install iperf3"
    exit 1
fi

# Get server IP address
SERVER_IP=$(hostname -I | awk '{print $1}')
if [ -z "$SERVER_IP" ]; then
    SERVER_IP="$(ip route get 1 | awk '{print $7; exit}')"
fi

log_message "Starting Network Speed Test Server"
log_message "Server IP: $SERVER_IP"
log_message "Server Port: $SERVER_PORT"
log_message "Waiting for connections..."
log_message "Press Ctrl+C to stop the server"

# Start iperf3 server in daemon mode
iperf3 -s -p $SERVER_PORT -D --logfile "$LOG_FILE"
iperf_pid=$!

if [ $? -eq 0 ]; then
    log_message "Server started successfully (PID: $iperf_pid)"
    log_message "Clients can connect using: $SERVER_IP:$SERVER_PORT"
    
    # Keep the script running
    while true; do
        sleep 60
        # Check if iperf3 is still running
        if ! ps -p $iperf_pid > /dev/null 2>&1; then
            log_message "iperf3 server stopped unexpectedly, restarting..."
            iperf3 -s -p $SERVER_PORT -D --logfile "$LOG_FILE"
            iperf_pid=$!
        fi
    done
else
    log_message "Failed to start iperf3 server"
    exit 1
fi