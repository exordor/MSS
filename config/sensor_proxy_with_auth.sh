#!/bin/bash
# Generate Digest Auth header for Time Machine
# Usage: ./get_digest_auth.sh <username> <password> <realm> <uri> <nonce>
# This is a helper script to demonstrate how Digest auth works

USERNAME="admin"  # Change to your username
PASSWORD="admin"  # Change to your password
REALM="Server authentication required"  # May vary, check browser dev tools
URI="/"

# Function to generate Digest auth response
generate_digest() {
    local username=$1
    local password=$2
    local realm=$3
    local uri=$4
    local nonce=$5

    # HA1 = MD5(username:realm:password)
    local ha1=$(echo -n "${username}:${realm}:${password}" | md5sum | cut -d' ' -f1)

    # HA2 = MD5(method:uri)
    local ha2=$(echo -n "GET:${uri}" | md5sum | cut -d' ' -f1)

    # Response = MD5(HA1:nonce:HA2)
    local response=$(echo -n "${ha1}:${nonce}:${ha2}" | md5sum | cut -d' ' -f1)

    echo "Digest username=\"${username}\", realm=\"${realm}\", nonce=\"${nonce}\", uri=\"${uri}\", response=\"${response}\""
}

# Example usage (you need to capture the nonce from the server's 401 response first)
# generate_digest "$USERNAME" "$PASSWORD" "$REALM" "$URI" "<captured_nonce>"
