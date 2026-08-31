"""Order line validation and the order state machine."""

import unittest

from fulfillment.errors import InvalidTransition, ValidationError
from fulfillment.models import (
    Order,
    OrderLine,
    OrderStatus,
    merge_lines,
)


def an_order(**kw):
    kw.setdefault("session_id", "live-1")
    kw.setdefault("lines", (OrderLine("sku-a", 1, 100),))
    return Order(**kw)


class OrderLineValidation(unittest.TestCase):
    def test_rejects_non_positive_quantity(self):
        for bad in (0, -3):
            with self.subTest(quantity=bad), self.assertRaises(ValidationError):
                OrderLine("sku-a", bad)

    def test_rejects_bool_quantity(self):
        # bool is an int subclass; True would silently mean "one unit".
        with self.assertRaises(ValidationError):
            OrderLine("sku-a", True)

    def test_rejects_blank_sku_and_negative_price(self):
        with self.assertRaises(ValidationError):
            OrderLine("   ", 1)
        with self.assertRaises(ValidationError):
            OrderLine("sku-a", 1, -1)

    def test_subtotal(self):
        self.assertEqual(OrderLine("sku-a", 3, 250).subtotal_cents, 750)


class OrderBasics(unittest.TestCase):
    def test_requires_session_and_lines(self):
        with self.assertRaises(ValidationError):
            an_order(session_id="")
        with self.assertRaises(ValidationError):
            an_order(lines=())

    def test_totals_and_seed_history(self):
        order = an_order(lines=(OrderLine("a", 2, 300), OrderLine("b", 1, 150)))
        self.assertEqual(order.total_cents, 750)
        self.assertEqual(order.unit_count, 3)
        self.assertEqual(order.status, OrderStatus.CAPTURED)
        self.assertEqual(len(order.history), 1)
        self.assertIsNone(order.history[0].from_status)


class OrderStateMachine(unittest.TestCase):
    def test_happy_path_records_audit_trail(self):
        order = an_order()
        order.transition_to(OrderStatus.RESERVED, "stock held")
        order.transition_to(OrderStatus.FULFILLED, "shipped")
        self.assertEqual(order.status, OrderStatus.FULFILLED)
        self.assertEqual(
            [c.to_status for c in order.history],
            [OrderStatus.CAPTURED, OrderStatus.RESERVED, OrderStatus.FULFILLED],
        )
        self.assertEqual(order.history[-1].reason, "shipped")

    def test_cannot_fulfil_without_reserving(self):
        order = an_order()
        with self.assertRaises(InvalidTransition):
            order.transition_to(OrderStatus.FULFILLED)

    def test_terminal_statuses_are_final(self):
        for terminal in (OrderStatus.CANCELLED, OrderStatus.FAILED):
            with self.subTest(status=terminal):
                order = an_order()
                order.transition_to(terminal)
                self.assertTrue(order.is_terminal)
                with self.assertRaises(InvalidTransition):
                    order.transition_to(OrderStatus.RESERVED)

    def test_failed_transition_leaves_order_untouched(self):
        order = an_order()
        before = order.status, len(order.history), order.updated_at
        with self.assertRaises(InvalidTransition):
            order.transition_to(OrderStatus.FULFILLED)
        self.assertEqual((order.status, len(order.history), order.updated_at), before)

    def test_reserved_order_can_fail(self):
        # Payment declines land after stock is already held, so RESERVED must
        # reach FAILED without being laundered through CANCELLED.
        order = an_order()
        order.transition_to(OrderStatus.RESERVED)
        order.transition_to(OrderStatus.FAILED, "payment declined")
        self.assertEqual(order.status, OrderStatus.FAILED)
        self.assertTrue(order.is_terminal)

    def test_cancelled_and_failed_stay_distinct(self):
        # Both are terminal and both free stock, but reporting must be able to
        # tell a pulled order from a lost sale.
        self.assertNotEqual(OrderStatus.CANCELLED, OrderStatus.FAILED)
        for terminal in (OrderStatus.CANCELLED, OrderStatus.FAILED):
            with self.subTest(status=terminal):
                order = an_order()
                order.transition_to(OrderStatus.RESERVED)
                order.transition_to(terminal)
                self.assertEqual(order.history[-1].to_status, terminal)

    def test_holds_stock_only_while_reserved(self):
        order = an_order()
        self.assertFalse(order.holds_stock)
        order.transition_to(OrderStatus.RESERVED)
        self.assertTrue(order.holds_stock)
        order.transition_to(OrderStatus.FULFILLED)
        self.assertFalse(order.holds_stock)


class MergeLines(unittest.TestCase):
    def test_collapses_repeated_skus_keeping_first_price(self):
        merged = merge_lines(
            [OrderLine("a", 1, 100), OrderLine("b", 4, 50), OrderLine("a", 2, 999)]
        )
        by_sku = {line.sku: line for line in merged}
        self.assertEqual(len(merged), 2)
        self.assertEqual(by_sku["a"].quantity, 3)
        self.assertEqual(by_sku["a"].unit_price_cents, 100)
        self.assertEqual(by_sku["b"].quantity, 4)


if __name__ == "__main__":
    unittest.main()
