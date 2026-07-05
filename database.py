"""Работа с SQLite для хранения путешествий и расходов."""

import sqlite3
from typing import Optional


class TravelDB:
    def __init__(self, db_name: str = "travel_wallet.db"):
        self.db_name = db_name
        self._create_tables()

    def _connect(self):
        return sqlite3.connect(self.db_name, check_same_thread=False)

    def _create_tables(self):
        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                home_currency TEXT NOT NULL,
                dest_currency TEXT NOT NULL,
                rate REAL NOT NULL,
                home_balance REAL NOT NULL,
                dest_balance REAL NOT NULL,
                is_active INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id INTEGER NOT NULL,
                amount_dest REAL NOT NULL,
                amount_home REAL NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
            )
            """
        )

        conn.commit()
        conn.close()

    def create_trip(
        self,
        user_id: int,
        name: str,
        home_currency: str,
        dest_currency: str,
        rate: float,
        home_balance: float,
        dest_balance: float,
    ) -> int:
        """Создаёт новое путешествие и делает его активным для пользователя."""
        conn = self._connect()
        cursor = conn.cursor()

        # Сбрасываем активность всех поездок пользователя
        cursor.execute(
            "UPDATE trips SET is_active = 0 WHERE user_id = ?",
            (user_id,),
        )

        cursor.execute(
            """
            INSERT INTO trips
            (user_id, name, home_currency, dest_currency, rate, home_balance, dest_balance, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                user_id,
                name,
                home_currency.upper(),
                dest_currency.upper(),
                rate,
                home_balance,
                dest_balance,
            ),
        )

        trip_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return trip_id

    def get_trips(self, user_id: int) -> list[dict]:
        """Возвращает все путешествия пользователя."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM trips WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_active_trip(self, user_id: int) -> Optional[dict]:
        """Возвращает активное путешествие пользователя."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM trips WHERE user_id = ? AND is_active = 1 LIMIT 1",
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def set_active_trip(self, user_id: int, trip_id: int) -> bool:
        """Делает указанное путешествие активным."""
        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT 1 FROM trips WHERE id = ? AND user_id = ?",
            (trip_id, user_id),
        )
        if not cursor.fetchone():
            conn.close()
            return False

        cursor.execute(
            "UPDATE trips SET is_active = 0 WHERE user_id = ?",
            (user_id,),
        )
        cursor.execute(
            "UPDATE trips SET is_active = 1 WHERE id = ?",
            (trip_id,),
        )
        conn.commit()
        conn.close()
        return True

    def update_rate(self, trip_id: int, new_rate: float) -> None:
        """Обновляет курс и пересчитывает баланс в валюте назначения."""
        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT home_balance FROM trips WHERE id = ?",
            (trip_id,),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            raise ValueError("Путешествие не найдено")

        home_balance = row[0]
        new_dest_balance = home_balance * new_rate

        cursor.execute(
            "UPDATE trips SET rate = ?, dest_balance = ? WHERE id = ?",
            (new_rate, new_dest_balance, trip_id),
        )
        conn.commit()
        conn.close()

    def add_expense(
        self,
        trip_id: int,
        amount_dest: float,
        amount_home: float,
        description: str = "",
    ) -> None:
        """Записывает расход и уменьшает баланс путешествия."""
        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT home_balance, dest_balance FROM trips WHERE id = ?",
            (trip_id,),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            raise ValueError("Путешествие не найдено")

        home_balance, dest_balance = row
        new_home_balance = home_balance - amount_home
        new_dest_balance = dest_balance - amount_dest

        cursor.execute(
            """
            INSERT INTO expenses (trip_id, amount_dest, amount_home, description)
            VALUES (?, ?, ?, ?)
            """,
            (trip_id, amount_dest, amount_home, description),
        )
        cursor.execute(
            """
            UPDATE trips
            SET home_balance = ?, dest_balance = ?
            WHERE id = ?
            """,
            (new_home_balance, new_dest_balance, trip_id),
        )

        conn.commit()
        conn.close()

    def get_expenses(self, trip_id: int, limit: int = 20) -> list[dict]:
        """Возвращает последние расходы по путешествию."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM expenses
            WHERE trip_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (trip_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_trip(self, trip_id: int) -> Optional[dict]:
        """Возвращает путешествие по id."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trips WHERE id = ?", (trip_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
