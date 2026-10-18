from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import KnowledgeGraphEdge, KnowledgeGraphNode, Tenant
from app.services.knowledge_graph_service import KnowledgeGraphService


def test_connected_nodes_rank_before_old_isolates_and_stale_edges_do_not_count():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id=1, external_id='connected-test'))
        db.flush()
        db.info['tenant_id'] = 1
        nodes = [KnowledgeGraphNode(tenant_id=1, node_key=f'n:{i}', node_type='company' if i < 4 else 'principle', label=f'N{i}') for i in range(6)]
        db.add_all(nodes)
        db.flush()
        for source, target, status in [(4, 5, 'active'), (5, 3, 'active'), (0, 1, 'stale'), (0, 2, 'stale')]:
            db.add(KnowledgeGraphEdge(tenant_id=1, from_node_id=nodes[source].id, to_node_id=nodes[target].id, edge_type='linked', status=status))
        db.commit()
        graph = KnowledgeGraphService().graph(db, limit=2)
        assert [node['id'] for node in graph['nodes']] == [nodes[5].id, nodes[3].id]
        assert graph['edge_count'] == 1
        assert graph['total_node_count'] == 6
        assert len(KnowledgeGraphService().graph(db, limit=6)['nodes']) == 6
        # A relation to an excluded type does not inflate in-scope degree.
        scoped = KnowledgeGraphService().graph(db, node_types={'company'}, limit=2)
        assert [node['id'] for node in scoped['nodes']] == [nodes[0].id, nodes[1].id]
        assert scoped['edge_count'] == 0
    engine.dispose()
