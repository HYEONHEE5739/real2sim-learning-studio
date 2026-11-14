"""Display-only collision topology. No mesh edits, CSG, or renderer ownership.

Adjacency uses exact authored coordinates. Contacts are joined for feature
analysis only when closed parts have identical, oppositely oriented patches.
"""
from collections import defaultdict
import numpy as np


def _root(parent,i):
    while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
    return i


def mesh_topology(vertices,faces):
    vertices=np.asarray(vertices,float).reshape(-1,3);faces=np.asarray(faces,int).reshape(-1,3)
    if not np.isfinite(vertices).all()or np.any(faces<0)or np.any(faces>=len(vertices)):
        raise ValueError('Finite collision vertices and valid triangle indices required')
    points,inverse=np.unique(vertices,axis=0,return_inverse=True);faces=inverse[faces]
    triangles=points[faces];cross=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    lengths=np.linalg.norm(cross,axis=1)
    side2=np.maximum(np.sum((triangles[:,1]-triangles[:,0])**2,axis=1),np.sum((triangles[:,2]-triangles[:,0])**2,axis=1))
    valid=lengths>64*np.finfo(float).eps*side2
    degenerate=int((~valid).sum());faces=faces[valid];normals=cross[valid]/lengths[valid,None]
    _,first=np.unique(np.sort(faces,axis=1),axis=0,return_index=True);first=np.sort(first)
    duplicates=len(faces)-len(first);faces=faces[first];normals=normals[first]
    edges=defaultdict(list);orientations=defaultdict(int)
    for i,face in enumerate(faces):
        for a,b in [(0,1),(1,2),(2,0)]:
            edge=tuple(sorted((face[a],face[b])));edges[edge].append(i)
            orientations[edge]+=1 if face[a]<face[b]else-1
    pairs=np.array(list(edges),int).reshape(-1,2)
    center=points.mean(0)if len(points)else np.zeros(3);tri=points[faces]-center
    volume=float(np.einsum('ij,ij->i',tri[:,0],np.cross(tri[:,1],tri[:,2])).sum())/6
    extent=np.linalg.norm(np.ptp(points,axis=0))if len(points)else 0.
    closed=(bool(edges)and all(len(a)==2 for a in edges.values())and not any(orientations.values())
        and abs(volume)>64*np.finfo(float).eps*extent**3)
    if closed and volume<0:normals=-normals  # Analysis only; authored faces stay intact.
    return {'points':points,'faces':faces,'normals':normals,'adjacency':edges,'segments':points[pairs],
        'closed':closed,'ignored_degenerate':degenerate,'ignored_duplicate':duplicates}


def collision_topology(meshes):
    """Cache all edges and a contact-aware surface adjacency once per payload."""
    parts=[];patches=defaultdict(list)
    for index,mesh in enumerate(meshes):
        if mesh['kind']!='collision':continue
        part=mesh_topology(mesh['vertices'],mesh['faces']);part['part_index']=index;parts.append(part)
        if not part['closed']:continue
        faces=part['faces'];normals=part['normals'];parent=list(range(len(faces)))
        for adjacent in part['adjacency'].values():
            if len(adjacent)==2 and normals[adjacent[0]]@normals[adjacent[1]]>1-1e-10:
                parent[_root(parent,adjacent[0])]=_root(parent,adjacent[1])
        groups=defaultdict(set)
        for i in range(len(faces)):groups[_root(parent,i)].add(i)
        boundaries=defaultdict(list)
        for edge,adjacent in part['adjacency'].items():
            attached=defaultdict(int)
            for i in adjacent:attached[_root(parent,i)]+=1
            for group,count in attached.items():
                if count==1:boundaries[group].append(tuple(sorted(tuple(p)for p in part['points'][list(edge)])))
        for group,ids in groups.items():
            boundary=boundaries[group]
            if boundary:patches[tuple(sorted(boundary))].append((index,ids,normals[list(ids)].mean(0)))
    parents={p['part_index']:p['part_index']for p in parts};internal=defaultdict(set);contacts=0
    for matches in patches.values():
        # Ambiguous/multiple coincident patches stay separate for review.
        if len(matches)!=2:continue
        (a,fa,na),(b,fb,nb)=matches
        if a==b or na@nb>=-1+1e-10:continue
        internal[a].update(fa);internal[b].update(fb)
        parents[_root(parents,a)]=_root(parents,b);contacts+=1
    groups=defaultdict(list);segments={};owners={}
    for part in parts:
        index=part['part_index'];component=_root(parents,index)
        for i,face in enumerate(part['faces']):
            if i in internal[index]:continue
            for a,b in [(0,1),(1,2),(2,0)]:
                pair=tuple(sorted(tuple(p)for p in part['points'][face[[a,b]]]))
                key=(component,pair)
                groups[key].append(part['normals'][i]);segments[key]=pair;owners.setdefault(key,index)
    lines=[];normals=[];fixed=[];cosine=[];owner=[];nonmanifold=0
    for key,adjacent in groups.items():
        lines.append(segments[key]);owner.append(owners[key]);fixed.append(len(adjacent)!=2)
        if len(adjacent)>2:nonmanifold+=1
        normals.append([adjacent[0],adjacent[1]if len(adjacent)>1 else adjacent[0]])
        cosine.append(float(np.clip(adjacent[0]@adjacent[1],-1,1))if len(adjacent)==2 else 1.)
    return {'parts':parts,'segments':np.asarray(lines,float).reshape(-1,2,3),
        'normals':np.asarray(normals,float).reshape(-1,2,3),'fixed':np.asarray(fixed,bool),
        'cosine':np.asarray(cosine,float),'owner_parts':np.asarray(owner,int),
        'contact_patch_pairs':contacts,'nonmanifold_edges':nonmanifold,
        'ignored_degenerate':sum(p['ignored_degenerate']for p in parts),
        'ignored_duplicate':sum(p['ignored_duplicate']for p in parts)}


def feature_base(topology,angle):
    if not np.isfinite(angle)or not 0<=angle<=180:raise ValueError('Feature Angle must be 0..180 degrees')
    return topology['fixed']|(topology['cosine']<=np.cos(np.radians(angle)))


def silhouette_mask(topology,direction):
    direction=np.asarray(direction,float)
    if direction.shape!=(3,)or not np.isfinite(direction).all()or np.linalg.norm(direction)==0:
        raise ValueError('Finite nonzero camera direction required')
    facing=topology['normals']@(direction/np.linalg.norm(direction))
    return (facing.min(1)<=1e-10)&(facing.max(1)>=-1e-10)&(abs(facing).max(1)>1e-10)


def feature_mask(topology,angle,direction):
    return feature_base(topology,angle)|silhouette_mask(topology,direction)
