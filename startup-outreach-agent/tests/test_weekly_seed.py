from unittest.mock import Mock
from datetime import datetime,timezone
from startup_agent.discovery.y_combinator import YCombinatorDiscoverySource

def test_weekly_yc_seed_batches_and_nonhiring_pagination(tmp_path):
    client=Mock()
    client.get.return_value.text='window.AlgoliaOpts = {"app":"fixture","key":"public-search-key"};'
    hit={'objectID':'1','name':'Studio','website':'https://studio.example','slug':'studio','team_size':15,'batch':'Winter 2024','isHiring':False}
    client.post.return_value.json.side_effect=[{'hits':[hit],'nbPages':2},{'hits':[],'nbPages':2}]
    path=tmp_path/'seed.txt'
    source=YCombinatorDiscoverySource(http_client=client,include_jobs=False,include_non_hiring=True,batches=['W24','S26','F26'],
        max_pages=8,seed_state_path=path,target_region_groups=[['India']])
    result=source.discover()
    assert len(result.companies)==1 and not result.jobs
    assert source.batches==['Winter 2024','Summer 2026','Fall 2026']
    assert client.post.call_count==2
    assert 'isHiring' not in client.post.call_args.kwargs['json_data']['params']
    assert not path.exists()  # pipeline writes the checkpoint only after persistence
    path.write_text(datetime.now(timezone.utc).isoformat())
    source.discover()
    assert client.post.call_count==2
