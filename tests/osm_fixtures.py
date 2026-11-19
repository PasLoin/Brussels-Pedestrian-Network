from build_graph import build_graph
from clean_osm import clean_osm


def one_way_per_case_xml(cases):
    nodes, ways = [], []
    for i, (name, tags) in enumerate(cases):
        lat = 50.80 + i * 0.002
        a, b = 2 * i + 1, 2 * i + 2
        nodes.append(f'<node id="{a}" lat="{lat:.4f}" lon="4.3000" version="1"/>')
        nodes.append(f'<node id="{b}" lat="{lat:.4f}" lon="4.3010" version="1"/>')
        tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        ways.append(
            f'<way id="{100 + i}" version="1"><nd ref="{a}"/><nd ref="{b}"/>'
            f'<tag k="name" v="{name}"/>{tag_xml}</way>'
        )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n<osm version=\"0.6\" generator=\"test\">\n"
        + "\n".join(nodes) + "\n" + "\n".join(ways) + "\n</osm>\n"
    )


def cleaned_graph(folder, osm_xml):
    raw, clean = folder / "raw.osm", folder / "clean.osm"
    raw.write_text(osm_xml)
    clean_osm(str(raw), str(clean))
    return build_graph(str(clean))
