#!/bin/bash

# Network Speed Test Client
# Usage: ./network_speed_client.sh <server_ip>

SERVER_PORT=5201
TEST_DURATION=10  # seconds for each test
PARALLEL_STREAMS=4

# Function to print usage
usage() {
    echo "Usage: $0 <server_ip> [options]"
    echo ""
    echo "Options:"
    echo "  -d, --duration SECONDS    Test duration (default: $TEST_DURATION)"
    echo "  -p, --parallel STREAMS    Number of parallel streams (default: $PARALLEL_STREAMS)"
    echo "  -h, --help               Show this help message"
    echo ""
    echo "Example:"
    echo "  $0 192.168.1.100"
    echo "  $0 192.168.1.100 -d 15 -p 8"
}

# Function to check if server is reachable
check_server() {
    local server_ip=$1
    if ! ping -c 1 -W 2 "$server_ip" &> /dev/null; then
        echo "Error: Cannot reach server at $server_ip"
        return 1
    fi
    
    # Check if iperf3 server is running on the target
    if ! nc -z -w 3 "$server_ip" "$SERVER_PORT" &> /dev/null; then
        echo "Error: iperf3 server not running on $server_ip:$SERVER_PORT"
        echo "Make sure the server script is running on the target machine"
        return 1
    fi
    return 0
}

# Function to run speed test
run_speed_test() {
    local server_ip=$1
    local test_type=$2  # "download" or "upload"
    local duration=$3
    local streams=$4
    
    echo ""
    echo "=== Testing $test_type speed ==="
    
    if [ "$test_type" == "download" ]; then
        # Download test (server sends to client)
        iperf3 -c "$server_ip" -p $SERVER_PORT -t "$duration" -P "$streams" -R
    else
        # Upload test (client sends to server)
        iperf3 -c "$server_ip" -p $SERVER_PORT -t "$duration" -P "$streams"
    fi
}

# Function to format speed results
format_speed() {
    local speed=$1
    if (( $(echo "$speed > 1000" | bc -l) )); then
        echo "$(echo "scale=2; $speed / 1000" | bc -l) Gbits/sec"
    else
        echo "$speed Mbits/sec"
    fi
}

# Parse command line arguments
SERVER_IP=""
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--duration)
            TEST_DURATION="$2"
            shift 2
            ;;
        -p|--parallel)
            PARALLEL_STREAMS="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            echo "Unknown option $1"
            usage
            exit 1
            ;;
        *)
            SERVER_IP="$1"
            shift
            ;;
    esac
done

# Validate server IP
if [ -z "$SERVER_IP" ]; then
    echo "Error: Server IP address is required"
    usage
    exit 1
fi

# Validate IP format (basic check)
if ! [[ $SERVER_IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Invalid IP address format: $SERVER_IP"
    exit 1
fi

# Check if iperf3 is installed
if ! command -v iperf3 &> /dev/null; then
    echo "Error: iperf3 is required but not installed."
    echo "Install it with:"
    echo "  Ubuntu/Debian: sudo apt-get install iperf3"
    echo "  CentOS/RHEL: sudo yum install iperf3"
    echo "  macOS: brew install iperf3"
    exit 1
fi

# Check if bc is installed for calculations
if ! command -v bc &> /dev/null; then
    echo "Error: bc is required but not installed."
    echo "Install it with:"
    echo "  Ubuntu/Debian: sudo apt-get install bc"
    echo "  CentOS/RHEL: sudo yum install bc"
    echo "  macOS: brew install bc"
    exit 1
fi

# Check server availability
echo "Checking server connectivity..."
if ! check_server "$SERVER_IP"; then
    exit 1
fi

echo "Server connection successful!"
echo "Test Configuration:"
echo "  Server: $SERVER_IP:$SERVER_PORT"
echo "  Duration: $TEST_DURATION seconds per test"
echo "  Parallel Streams: $PARALLEL_STREAMS"
echo ""

# Run download test
run_speed_test "$SERVER_IP" "download" "$TEST_DURATION" "$PARALLEL_STREAMS"

# Run upload test  
run_speed_test "$SERVER_IP" "upload" "$TEST_DURATION" "$PARALLEL_STREAMS"

echo ""
echo "Speed test completed!"