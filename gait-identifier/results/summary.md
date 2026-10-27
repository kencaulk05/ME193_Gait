# Results

**Data:** 16 recordings (Kendrick, Marie), 3712 windows of 2 seconds (every 0.5 s) after trimming 1 s from each end of every recording. No recording was skipped.

Neighbouring windows overlap by 75%, so the number of independent test windows is about a quarter of the counts below; read differences of a few percent as noise.

## Accuracy

| Test | Model A, feature chosen from the training data only (fair) | Model A, feature `ax_max` chosen using everyone (optimistic) | Model B (all six outputs) | Extra: random forest on B's numbers |
|---|---|---|---|---|
| New person: trained on Marie, tested on Kendrick | 69.8% (it chose ay_min) | 82.3% | 93.9% | 94.6% |
| New person: trained on Kendrick, tested on Marie | 60.4% (it chose ax_min) | 84.4% | 99.2% | 98.4% |
| **New person, average** | **65.1%** | **83.3%** | **96.6%** | 96.5% |
| New recording, same people: trained on recording 2 of everyone, tested on recording 1 of everyone | 85.5% (it chose ax_min) | 85.5% | 97.1% | 97.5% |
| New recording, same people: trained on recording 1 of everyone, tested on recording 2 of everyone | 83.8% (it chose ax_max) | 83.8% | 98.3% | 99.5% |
| **New recording, same people, average** | **84.6%** | **84.7%** | **97.7%** | 98.5% |

'New person' is the hard test: it is what your graders will be. With only two people, Model A's number can be chosen fairly only from ONE person's recordings, and that choice does not transfer (first column). The model on the board uses `ax_max`, chosen with both people's data, so its second-column score is optimistic. The truth for a new person lies between the two columns; a third person recorded would settle it.

## What each model gets wrong (new-person tests, pooled; rows = what really happened)

**Model A, fair feature choice**

| really \ predicted | still | walk | run | bike | correct |
|---|---|---|---|---|---|
| still | 69 | 0 | 0 | 859 | 7% |
| walk | 0 | 782 | 146 | 0 | 84% |
| run | 0 | 73 | 855 | 0 | 92% |
| bike | 201 | 16 | 0 | 711 | 77% |

**Model A, the deployed feature (optimistic)**

| really \ predicted | still | walk | run | bike | correct |
|---|---|---|---|---|---|
| still | 928 | 0 | 0 | 0 | 100% |
| walk | 0 | 776 | 152 | 0 | 84% |
| run | 0 | 135 | 611 | 182 | 66% |
| bike | 0 | 0 | 150 | 778 | 84% |

**Model B**

| really \ predicted | still | walk | run | bike | correct |
|---|---|---|---|---|---|
| still | 928 | 0 | 0 | 0 | 100% |
| walk | 0 | 914 | 14 | 0 | 98% |
| run | 0 | 109 | 819 | 0 | 88% |
| bike | 0 | 4 | 0 | 924 | 100% |

## The final models (trained on all the data, for the board)

* **Model A** looks at `ax_max` only. Thresholds: -0.84, -0.24, 0.27 g.

* **Model B** uses these numbers (share of the tree's decisions): `ay_min` 34%, `ay_max` 34%, `acc_mean` 30%, `gyro_std` 1%.

The final models were trained on everything, so they have no honest test score of their own: the tables above are the evidence.
