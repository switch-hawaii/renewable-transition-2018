#!/bin/bash

#SBATCH --job-name=switch_eval
#SBATCH --partition=kill.q
#SBATCH --time=3-00:00:00
#SBATCH --cpus-per-task=1
#SBATCH --ntasks=380
#SBATCH --mail-user=mfripp@hawaii.edu
#SBATCH --mail-type=END
#SBATCH --output=logs/%A.out
#SBATCH --error=logs/%A.err
#SBATCH --mem-per-cpu=6400

module load lang/Python/2.7.10/python
module load openmpi

python solve_loop.py
