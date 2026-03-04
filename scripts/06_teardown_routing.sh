#!/bin/bash
sudo pfctl -d
sudo sysctl -w net.inet.ip.forwarding=0
echo "ルーティング解除完了"
