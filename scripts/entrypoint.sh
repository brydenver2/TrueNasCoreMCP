#!/bin/bash

# TrueNAS MCP Server Entrypoint Script
# Handles optional Tailscale activation and Uvicorn startup

set -euo pipefail

# Default values
TAILSCALE_ENABLED="${TAILSCALE_ENABLED:-false}"
TAILSCALE_STATE_DIR="${TAILSCALE_STATE_DIR:-/var/lib/tailscale}"
TAILSCALE_TIMEOUT="${TAILSCALE_TIMEOUT:-30}"
TAILSCALE_SOCK="/tmp/tailscaled.sock"

# Logging function
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

# Error handling function
error_exit() {
    log "ERROR: $*"
    exit 1
}

# Cleanup function for graceful shutdown
cleanup() {
    log "Received shutdown signal, cleaning up..."
    if [[ "${TAILSCALE_ENABLED}" == "true" ]]; then
        log "Stopping Tailscale..."
        tailscale down 2>/dev/null || true
        pkill -f tailscaled 2>/dev/null || true
    fi
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# Function to read from file or environment variable
get_config_value() {
    local var_name="$1"
    local file_var_name="${var_name}_FILE"
    local file_path="${!file_var_name:-}"
    
    if [[ -n "${file_path}" && -f "${file_path}" ]]; then
        cat "${file_path}"
    else
        echo "${!var_name:-}"
    fi
}

# Function to validate Tailscale configuration
validate_tailscale_config() {
    log "Validating Tailscale configuration..."
    
    local auth_key
    auth_key=$(get_config_value "TAILSCALE_AUTH_KEY")
    
    if [[ -z "${auth_key}" ]]; then
        error_exit "TAILSCALE_AUTH_KEY is required when Tailscale is enabled"
    fi
    
    log "Tailscale configuration validated successfully"
}

# Function to start Tailscaled daemon
start_tailscaled() {
    log "Starting Tailscaled daemon..."
    
    # Create state directory if it doesn't exist
    mkdir -p "${TAILSCALE_STATE_DIR}"
    
    # Start tailscaled with custom socket
    tailscaled \
        --state="${TAILSCALE_STATE_DIR}" \
        --socket="${TAILSCALE_SOCK}" \
        --port=41641 \
        --tun=userspace-networking &
    
    local tailscaled_pid=$!
    log "Tailscaled started with PID: ${tailscaled_pid}"
    
    # Wait for socket to be created
    local wait_time=0
    while [[ ! -S "${TAILSCALE_SOCK}" ]] && [[ $wait_time -lt ${TAILSCALE_TIMEOUT} ]]; do
        sleep 1
        wait_time=$((wait_time + 1))
    done
    
    if [[ ! -S "${TAILSCALE_SOCK}" ]]; then
        error_exit "Tailscaled socket not found after ${TAILSCALE_TIMEOUT} seconds"
    fi
    
    log "Tailscaled socket is ready at ${TAILSCALE_SOCK}"
}

# Function to connect to Tailscale
connect_tailscale() {
    log "Connecting to Tailscale..."
    
    local auth_key
    auth_key=$(get_config_value "TAILSCALE_AUTH_KEY")
    
    # Build tailscale up command
    local tailscale_cmd="tailscale --socket=${TAILSCALE_SOCK} up --authkey=${auth_key}"
    
    # Add optional hostname
    if [[ -n "${TAILSCALE_HOSTNAME:-}" ]]; then
        tailscale_cmd="${tailscale_cmd} --hostname=${TAILSCALE_HOSTNAME}"
    fi
    
    # Add optional tags
    if [[ -n "${TAILSCALE_TAGS:-}" ]]; then
        tailscale_cmd="${tailscale_cmd} --advertise-tags=${TAILSCALE_TAGS}"
    fi
    
    # Add extra args
    if [[ -n "${TAILSCALE_EXTRA_ARGS:-}" ]]; then
        tailscale_cmd="${tailscale_cmd} ${TAILSCALE_EXTRA_ARGS}"
    fi
    
    # Execute tailscale up
    log "Executing: tailscale up (auth key hidden)"
    eval "${tailscale_cmd}" || error_exit "Failed to connect to Tailscale"
    
    # Wait for connection
    local wait_time=0
    while ! tailscale --socket="${TAILSCALE_SOCK}" status >/dev/null 2>&1 && [[ $wait_time -lt ${TAILSCALE_TIMEOUT} ]]; do
        sleep 1
        wait_time=$((wait_time + 1))
    done
    
    if ! tailscale --socket="${TAILSCALE_SOCK}" status >/dev/null 2>&1; then
        error_exit "Tailscale connection not established after ${TAILSCALE_TIMEOUT} seconds"
    fi
    
    # Show status
    log "Tailscale connected successfully"
    tailscale --socket="${TAILSCALE_SOCK}" status | head -n 5
}

# Main execution
main() {
    log "Starting TrueNAS MCP Server..."
    
    # Read configuration with optional *_FILE overrides
    local truenas_url
    local truenas_api_key
    local mcp_access_token

    truenas_url=$(get_config_value "TRUENAS_URL")
    truenas_api_key=$(get_config_value "TRUENAS_API_KEY")
    mcp_access_token=$(get_config_value "MCP_ACCESS_TOKEN")
    
    # Validate required environment variables
    if [[ -z "${truenas_url}" ]]; then
        error_exit "TRUENAS_URL environment variable is required"
    fi
    
    if [[ -z "${truenas_api_key}" ]]; then
        error_exit "TRUENAS_API_KEY environment variable is required"
    fi
    
    if [[ -z "${mcp_access_token}" ]]; then
        error_exit "MCP_ACCESS_TOKEN environment variable is required"
    fi

    export TRUENAS_URL="${truenas_url}"
    export TRUENAS_API_KEY="${truenas_api_key}"
    export MCP_ACCESS_TOKEN="${mcp_access_token}"
    
    log "Environment validation passed"
    log "TrueNAS URL: ${truenas_url}"
    log "MCP Transport: ${MCP_TRANSPORT:-http}"
    
    # Handle Tailscale if enabled
    if [[ "${TAILSCALE_ENABLED}" == "true" ]]; then
        log "Tailscale integration: ENABLED"
        validate_tailscale_config
        start_tailscaled
        connect_tailscale
    else
        log "Tailscale integration: DISABLED"
    fi
    
    log "Starting application server..."
    log "Command: $*"
    
    # Execute the provided command (usually uvicorn)
    exec "$@"
}

# Run main function with all script arguments
main "$@"
