#!/usr/bin/env python3

import json
import numpy as np
import matplotlib.pyplot as plt


def get_end_time(path):
    text = open(path, "r").read().strip()

    # load the last JSON object in the file (in case output was appended)
    i = text.rfind("\n{")
    if i == -1:
        i = 0
    else:
        i = i + 1

    data = json.loads(text[i:])
    return data["end"]["sum_sent"]["end"]


def cdf(values):
    x = np.sort(np.array(values))
    y = np.arange(1, len(x) + 1) / len(x)
    return x, y


def main():
    prague = []
    bbr3 = []

    for i in range(1, 129):
        prague.append(get_end_time(f"20BDP/prague/hs{i}_out.json"))
        bbr3.append(get_end_time(f"20BDP/bbr/hs{i}_out.json"))

    x_p, y_p = cdf(prague)
    x_b, y_b = cdf(bbr3)

    plt.figure()
    plt.step(x_p, y_p, where="post", label="Prague")
    plt.step(x_b, y_b, where="post", label="BBR3")
    plt.xlabel("FCT (seconds)")
    plt.ylabel("CDF")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    plt.savefig("cdf_fct.pdf")   # saves in current directory
    # plt.show()  # optional


if __name__ == "__main__":
    main()
