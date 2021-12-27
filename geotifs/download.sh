#!/bin/bash
cat dem.csv | cut -d ',' -f '17' | xargs wget
