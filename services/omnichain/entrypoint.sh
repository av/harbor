#!/bin/bash

APP_PORT=12538
API_PORT=5002

# Function to stop socat processes
stop_socat() {
    echo "Stopping socat processes..."
    kill $(jobs -p)
    wait
}

# Function to forward signals to the main process
forward_signal() {
    kill -$1 $MAIN_PID
}

# Set up signal handling
trap 'stop_socat; forward_signal TERM; exit 0' TERM INT QUIT

# Start socat to forward traffic the service ports
socat TCP-LISTEN:${APP_PORT},fork TCP:localhost:${APP_PORT} &
socat TCP-LISTEN:${API_PORT},fork TCP:localhost:${API_PORT} &

# Start your actual application and get its PID
"$@" &
MAIN_PID=$!

# Wait for the main process to exit
wait $MAIN_PID

# Stop socat processes if they're still running
stop_socat

# Exit with the same status as the main process
exit $?
