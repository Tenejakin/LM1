"""LM1 0.5.1: open camera/Pi bench prototype with 28-degree downward pitch."""
import json
from pathlib import Path
import numpy as np
import trimesh
import lm1_case_v0_2_0 as cad

VERSION = '0.5.1'
OUT = Path(__file__).parent / 'stl' / 'v0.5.1-test'
CAMERA_PITCH_DEG = 28.0
cad.CASE_VERSION = VERSION
cad.CAMERA_PITCH_DEG = CAMERA_PITCH_DEG
B, C, U, D = cad.box, cad.cylinder, cad.union, cad.difference
PI_HOLES = [(x, y) for x in (-39, 19) for y in (63.5, 112.5)]
FOOT_HOLES = [(x, y) for x in (-55, 55) for y in (10, 34)]

def tray():
    pieces = [B((140,130,4),(0,65,2))]
    # Low corner bumpers stay below the elevated Pi PCB and its connectors.
    for x in (-67,67):
        pieces.append(B((6,130,3),(x,65,5.5)))
    for x,y in PI_HOLES:
        pieces.append(C(3.5,7,(x,y,7.5)))
    cuts = [C(1.4,15,(x,y,5)) for x,y in PI_HOLES]
    for x,y in FOOT_HOLES:
        cuts.append(C(1.7,12,(x,y,4)))
        cuts.append(C(3.2,2.2,(x,y,1.1)))
    # Tie-down/ballast slots, away from the PCB and camera foot.
    for x in (-52,52):
        cuts.append(B((4,18,12),(x,80,4)))
    return D(U(pieces),cuts)

def mast():
    # Wide flat foot with four through-bolts; two uprights keep ribbon access open.
    pieces=[B((130,32,4),(0,22,6))]
    for x in (-55,55):
        pieces.append(B((12,5,176),(x,20,96)))
        pieces.append(B((12,20,16),(x,22,16)))
    pieces.extend([B((122,5,8),(0,20,180)),B((122,5,8),(0,20,110))])
    cuts=[C(1.7,12,(x,y,6)) for x,y in FOOT_HOLES]
    for x in (-55,55):
        for z in (128,172):
            cuts.append(C(1.7,16,(x,20,z),axis=(0,1,0)))
    return D(U(pieces),cuts)

def component_count(mesh):
    parent=list(range(len(mesh.vertices)))
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]]
            x=parent[x]
        return x
    for a,b,c in mesh.faces:
        parent[find(int(b))]=find(int(a))
        parent[find(int(c))]=find(int(a))
    return len({find(i) for i in range(len(parent))})

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    base, stand = tray(),mast()
    bracket=cad.make_camera_mount()
    # Flange front at y=22.5 meets the mast rear at y=22.5.
    bracket.apply_translation((0,17.5,0))
    parts=[('pi_tray',base,'flat'),('camera_mast',stand,'side'),('camera_bracket_28deg',bracket,'side')]
    report={'version':VERSION,'units':'mm','camera_pitch_deg':CAMERA_PITCH_DEG,'parts':[]}
    for name,mesh,orientation in parts:
        printable=mesh.copy()
        if orientation=='side':
            printable.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2,(1,0,0)))
        printable=cad.on_bed(printable)
        printable.remove_unreferenced_vertices()
        file=f'lm1_test_{name}_v{VERSION}.stl'
        printable.export(OUT/file)
        # Reimport the actual STL so the checks cover export as well as CAD.
        checked=trimesh.load_mesh(OUT/file)
        item={'file':file,'watertight':bool(checked.is_watertight),
              'positive_volume':bool(checked.volume>0),'connected_solids':component_count(checked),
              'size_mm':np.round(checked.extents,2).tolist()}
        assert item['watertight'] and item['positive_volume'] and item['connected_solids']==1,item
        report['parts'].append(item)
    trimesh.util.concatenate([base,stand,bracket]).export(OUT/f'assembly_reference_v{VERSION}.stl')
    # Preview placeholders show where the electronics fit, not printed parts.
    pcb=B((85,56,1.6),(0,88,11.8))
    cooler=B((40,35,20),(-5,86,22.6))
    cad.render_preview([(base,(115,143,128)),(stand,(80,105,94)),
                       (bracket,(164,173,162)),(pcb,(38,126,72)),(cooler,(65,69,72))],
                      OUT/'preview.png')
    (OUT/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    main()
