from services.administrator_summary_collector import derive_attention_items
from services.system_storage import StorageStatus


def test_low_storage_adds_attention_item():
    items = derive_attention_items(
        (), (), (), (),
        StorageStatus(
            total_bytes=1000,
            used_bytes=900,
            free_bytes=100,
            percent_free=10.0,
            status="needs_attention",
        ),
    )

    assert len(items) == 1
    item = items[0]
    assert item.attention_code == "storage_low"
    assert item.free_bytes == 100
    assert item.percent_free == 10.0
    assert item.storage_status == "needs_attention"


def test_healthy_storage_does_not_add_attention_item():
    items = derive_attention_items(
        (), (), (), (),
        StorageStatus(
            total_bytes=1000,
            used_bytes=700,
            free_bytes=300,
            percent_free=30.0,
            status="healthy",
        ),
    )

    assert items == ()
