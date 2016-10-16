#!/bin/bash
#
# Creates the expected etcd directories for Commissaire

for x in clusters cluster hosts networks status; do
  etcd_path="commissaire/"$x
  echo "+ Creating $etcd_path"
  etcdctl mkdir $etcd_path
done

echo "+ Commissaire etcd namesapce now looks like the following:"
etcdctl ls --recursive /commissaire/
