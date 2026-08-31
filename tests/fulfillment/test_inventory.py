"""Stock ledger: atomic reservation, two-phase commit, and concurrency."""

import threading
import unittest

from fulfillment.errors import InsufficientStock, UnknownSku, ValidationError
from fulfillment.inventory import InventoryStore
from fulfillment.models import OrderLine


class Registration(unittest.TestCase):
    def test_initial_mapping_registers_skus(self):
        inv = InventoryStore({"a": 5, "b": 0})
        self.assertEqual(inv.available("a"), 5)
        self.assertEqual(inv.available("b"), 0)

    def test_duplicate_registration_rejected(self):
        inv = InventoryStore({"a": 1})
        with self.assertRaises(ValidationError):
            inv.add_product("a", 3)

    def test_unknown_sku_raises_everywhere(self):
        inv = InventoryStore()
        self.assertFalse(inv.knows("ghost"))
        with self.assertRaises(UnknownSku):
            inv.available("ghost")
        with self.assertRaises(UnknownSku):
            inv.reserve([OrderLine("ghost", 1)])

    def test_restock_adds_units(self):
        inv = InventoryStore({"a": 1})
        self.assertEqual(inv.restock("a", 4), 5)
        self.assertEqual(inv.available("a"), 5)
        with self.assertRaises(ValidationError):
            inv.restock("a", 0)


class Reservation(unittest.TestCase):
    def test_reserve_reduces_available_not_on_hand(self):
        inv = InventoryStore({"a": 10})
        inv.reserve([OrderLine("a", 4)])
        level = inv.level("a")
        self.assertEqual((level.on_hand, level.reserved, level.available), (10, 4, 6))

    def test_cannot_reserve_beyond_available(self):
        inv = InventoryStore({"a": 3})
        inv.reserve([OrderLine("a", 3)])
        with self.assertRaises(InsufficientStock) as ctx:
            inv.reserve([OrderLine("a", 1)])
        self.assertEqual(ctx.exception.available, 0)

    def test_multi_sku_reservation_is_all_or_nothing(self):
        inv = InventoryStore({"a": 5, "b": 1})
        with self.assertRaises(InsufficientStock):
            inv.reserve([OrderLine("a", 2), OrderLine("b", 9)])
        # 'a' must be untouched — a doomed basket may not strand another
        # buyer's units.
        self.assertEqual(inv.available("a"), 5)
        self.assertEqual(inv.available("b"), 1)

    def test_repeated_sku_in_one_basket_is_summed(self):
        inv = InventoryStore({"a": 3})
        with self.assertRaises(InsufficientStock):
            inv.reserve([OrderLine("a", 2), OrderLine("a", 2)])
        self.assertEqual(inv.available("a"), 3)


class TwoPhase(unittest.TestCase):
    def test_commit_depletes_on_hand_and_clears_hold(self):
        inv = InventoryStore({"a": 10})
        lines = [OrderLine("a", 4)]
        inv.reserve(lines)
        inv.commit(lines)
        level = inv.level("a")
        self.assertEqual((level.on_hand, level.reserved, level.available), (6, 0, 6))

    def test_release_returns_units_without_depleting(self):
        inv = InventoryStore({"a": 10})
        lines = [OrderLine("a", 4)]
        inv.reserve(lines)
        inv.release(lines)
        level = inv.level("a")
        self.assertEqual((level.on_hand, level.reserved, level.available), (10, 0, 10))

    def test_cannot_release_or_commit_more_than_held(self):
        inv = InventoryStore({"a": 10})
        inv.reserve([OrderLine("a", 2)])
        with self.assertRaises(ValidationError):
            inv.release([OrderLine("a", 3)])
        with self.assertRaises(ValidationError):
            inv.commit([OrderLine("a", 3)])
        self.assertEqual(inv.level("a").reserved, 2)


class Sync(unittest.TestCase):
    def test_reports_drift_and_registers_new_skus(self):
        inv = InventoryStore({"a": 5})
        drift = inv.sync({"a": 8, "new": 2})
        self.assertEqual(drift, {"a": 3, "new": 2})
        self.assertEqual(inv.available("a"), 8)
        self.assertTrue(inv.knows("new"))

    def test_unchanged_skus_are_not_reported_as_drift(self):
        inv = InventoryStore({"a": 5})
        self.assertEqual(inv.sync({"a": 5}), {})

    def test_refuses_to_sync_below_reserved_units(self):
        inv = InventoryStore({"a": 10})
        inv.reserve([OrderLine("a", 6)])
        with self.assertRaises(ValidationError):
            inv.sync({"a": 4})
        # The rejected sync must not have applied.
        self.assertEqual(inv.level("a").on_hand, 10)

    def test_rejects_negative_counts(self):
        inv = InventoryStore({"a": 1})
        with self.assertRaises(ValidationError):
            inv.sync({"a": -1})


class Concurrency(unittest.TestCase):
    def test_concurrent_reservations_never_oversell(self):
        """The scenario this module exists for: a live drop of 50 units with
        200 simultaneous buyers. Exactly 50 must succeed."""
        stock = 50
        buyers = 200
        inv = InventoryStore({"drop": stock})
        successes = []
        lock = threading.Lock()
        start = threading.Barrier(buyers)

        def buy():
            start.wait()
            try:
                inv.reserve([OrderLine("drop", 1)])
            except InsufficientStock:
                return
            with lock:
                successes.append(1)

        threads = [threading.Thread(target=buy) for _ in range(buyers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(successes), stock)
        self.assertEqual(inv.available("drop"), 0)
        self.assertEqual(inv.level("drop").reserved, stock)

    def test_concurrent_reserve_and_release_balances(self):
        inv = InventoryStore({"a": 100})
        errors = []

        def churn():
            lines = [OrderLine("a", 1)]
            for _ in range(200):
                try:
                    inv.reserve(lines)
                    inv.release(lines)
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

        threads = [threading.Thread(target=churn) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(inv.level("a").reserved, 0)
        self.assertEqual(inv.level("a").on_hand, 100)


if __name__ == "__main__":
    unittest.main()
