<!-- SPDX-License-Identifier: CC0-1.0 -->

# Open Know-How Metadata

Automatically create [Open Know-How](https://www.internetofproduction.org/openknowhow) metadata sidecar files alongside
your FreeCAD `*.FCStd` files.

# What is Open Know-How?

From the [Internet of Production](https://www.internetofproduction.org)'s site:

    Open Know-How is an open data model for sharing hardware designs and documentation online, to know how something can be made.

The upshot is that you can store information about the actual production of your open hardware design in a
sidecar file that can be read in by various bits of tooling designed to help people actually *make* the design.
For example, [Open Hardware Manager](https://www.openhardwaremanager.org/) can help you match open hardware designs to
manufacturing facilities and explore the resulting supply chains.

# Included Metadata

The Open Know-How [standard](https://github.com/iop-alliance/OpenKnowHow#standard) defines many pieces
of metadata that you can include in your model: this addon aims to support all of them.
