#!/bin/bash
# Test script to diagnose Container network issues

echo "=== Testing Container Network Access ==="
echo ""

echo "1. Testing DNS resolution..."
container run --rm python:3.12-slim nslookup pypi.org || echo "DNS test failed"

echo ""
echo "2. Testing HTTP connectivity to PyPI..."
container run --rm python:3.12-slim sh -c "apt-get update && apt-get install -y curl && curl -I https://pypi.org/simple/" || echo "HTTP test failed"

echo ""
echo "3. Testing pip connectivity..."
container run --rm python:3.12-slim pip install --timeout=30 requests || echo "Pip test failed"

echo ""
echo "4. Testing with build context..."
container build --platform linux/amd64 -f Dockerfile.test -t test-network . || echo "Build test failed"
