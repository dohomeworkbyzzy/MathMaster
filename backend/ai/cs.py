"""Bounded, deterministic 408 scratch tables; never advance unrequested steps."""
import ipaddress
from ..parser import MathInputError

def replacement(q):
 pages=q['pages'];end=len(pages) if q['run_remaining'] else min(len(pages),q['step']+q['steps'])
 if q['step']>len(pages):raise MathInputError('起始步超过引用串长度。')
 frames=[None]*q['frames'];ages=[-1]*q['frames'];faults=0;trace=[]
 for i,page in enumerate(pages[:end]):
  hit=page in frames;evicted=None
  if hit:
   slot=frames.index(page)
   if q['algorithm']=='LRU':ages[slot]=i
  else:
   faults+=1;slot=frames.index(None) if None in frames else min(range(q['frames']),key=lambda k:(ages[k],k))
   evicted=frames[slot];frames[slot]=page;ages[slot]=i
  if i>=q['step']:trace.append({'step':i+1,'page':page,'frames':frames[:],'fault':not hit,'evicted':evicted,'fault_count':faults})
 return {'algorithm':q['algorithm'],'trace':trace,'frames':frames,'fault_count':faults,'next_step':end,
  'completed':end==len(pages),'tie_break':'同龄时选择最低页框编号','verification_status':'deterministic_simulation'}

def graph(q):
 nodes=q['nodes'];source=q['source'];adj={n:[] for n in nodes}
 if len(set(nodes))!=len(nodes) or source not in nodes:raise MathInputError('顶点需唯一，起点必须存在。')
 for e in q['edges']:
  if e['u'] not in adj or e['v'] not in adj:raise MathInputError('边的顶点未在 nodes 声明。')
  adj[e['u']].append((e['v'],e['weight']))
  if not q['directed']:adj[e['v']].append((e['u'],e['weight']))
 for edges in adj.values():edges.sort(key=lambda e:(e[0],e[1]))
 seen=set();queue=[source];distance={source:0};parent={source:None};trace=[]
 end=len(nodes) if q['run_remaining'] else min(len(nodes),q['step']+q['steps'])
 for i in range(end):
  if q['algorithm']=='dijkstra':
   candidates=[n for n in distance if n not in seen]
   if not candidates:break
   node=min(candidates,key=lambda n:(distance[n],n))
  else:
   queue=[n for n in queue if n not in seen]
   if not queue:break
   node=queue.pop(0 if q['algorithm']=='bfs' else -1)
  seen.add(node)
  edges=adj[node] if q['algorithm']!='dfs' else list(reversed(adj[node]))
  for neighbour,weight in edges:
   if neighbour in seen:continue
   if q['algorithm']=='dijkstra':
    candidate=distance[node]+weight
    if neighbour not in distance or candidate<distance[neighbour]:distance[neighbour]=candidate;parent[neighbour]=node
   elif neighbour not in queue:
    distance[neighbour]=distance[node]+1;parent[neighbour]=node;queue.append(neighbour)
  if i>=q['step']:trace.append({'step':i+1,'vertex':node,'frontier':queue[:],
   'distance':dict(sorted(distance.items())),'predecessor':dict(sorted(parent.items())),'visited':sorted(seen)})
 if q['step']>len(seen):raise MathInputError('起始步超过可达顶点的执行长度。')
 remaining=any(n not in seen for n in distance) if q['algorithm']=='dijkstra' else any(n not in seen for n in queue)
 return {'algorithm':q['algorithm'],'trace':trace,'next_step':len(seen),'completed':not remaining,
  'distance':dict(sorted(distance.items())),'predecessor':dict(sorted(parent.items())),
  'tie_break':'顶点按字符串字典序；Dijkstra同距离按顶点字典序','verification_status':'deterministic_simulation'}

def subnet(q):
 try:network=ipaddress.IPv4Network(q['cidr'],strict=False)
 except ValueError:raise MathInputError('请输入明确的IPv4地址与CIDR前缀，例如192.168.1.70/26。') from None
 first,last=int(network.network_address),int(network.broadcast_address);size=network.num_addresses
 if q['host_convention']=='point_to_point' and network.prefixlen>=31:
  count=size;host_min=first;host_max=last
 else:
  count=max(0,size-2);host_min=first+1 if count else None;host_max=last-1 if count else None
 all_parts={'mask':{'prefix':network.prefixlen,'mask':str(network.netmask),'mask_binary':'.'.join(format(int(v),'08b') for v in str(network.netmask).split('.'))},
  'network':{'network':str(network.network_address),'broadcast':str(network.broadcast_address)},
  'hosts':{'usable_hosts':count,'first_host':str(ipaddress.IPv4Address(host_min)) if count else None,'last_host':str(ipaddress.IPv4Address(host_max)) if count else None}}
 result={}
 for part in all_parts:
  if q['part'] in ('all',part):result.update(all_parts[part])
 return {'fields':result,'host_convention':q['host_convention'],'verification_status':'integer_address_calculation',
  'warnings':['传统课堂口径保留网络与广播地址；/31和/32需按题干明确是否采用点到点口径。']}
