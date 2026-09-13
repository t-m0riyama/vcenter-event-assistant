"""Cursor encoding for collectors that resume where they left off.

アプリは ``next_cursor`` を不透明な文字列として保存し、次回 ``previous_cursor`` として
返すだけである。中身の意味付けはプラグインの責務であり、そこに 2 つの罠がある。

1. **空のバッチでカーソルを前進させないと、同じ範囲を永久に読み直す。**
2. **範囲の開始を少し戻さないと、境界上のイベントを取りこぼす。** 収集の実行時刻と
   イベントの発生時刻には差があり、前回の最大時刻と同一秒のイベントが後から現れうる。
   再読した分は ``vmware_key`` による重複排除で落ちるので、重ねる方が安全である。

``TimestampCursor`` は組み込みのイベントコレクタが使っている規則をそのまま公開する。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from vcenter_event_assistant_plugin_api.timeutils import now_utc


@dataclass(frozen=True, slots=True)
class TimestampCursor:
    """ISO 8601 のタイムスタンプ 1 つをカーソルとして扱う。

    Attributes:
        overlap: 取得範囲の開始をこれだけ戻す。重複排除が効いていることが前提。
        default_lookback: カーソルが無いときに遡る量。``None`` なら
            :meth:`window_start` は ``None`` を返し、初回の範囲は取得側に委ねる。
    """

    overlap: timedelta = timedelta(seconds=1)
    default_lookback: timedelta | None = None

    def decode(self, previous: str | None) -> datetime | None:
        """保存されていたカーソルを読む。壊れていれば ``None``（= 初回扱い）。

        カーソルは DB の文字列であり、書式を変えた直後や手で書き換えられた場合に
        読めないことがある。そこで収集全体を落とすより、初回として扱う方が回復しやすい。
        """
        if not previous:
            return None
        try:
            return datetime.fromisoformat(previous)
        except ValueError:
            return None

    def window_start(
        self, previous: str | None, *, now: datetime | None = None
    ) -> datetime | None:
        """取得範囲の開始時刻。``overlap`` だけ戻した値を返す。

        カーソルが無い場合は ``default_lookback`` があればそこから、無ければ ``None``
        （取得側の既定に任せる）。
        """
        decoded = self.decode(previous)
        if decoded is not None:
            return decoded - self.overlap
        if self.default_lookback is not None:
            return (now or now_utc()) - self.default_lookback
        return None

    def advance(
        self,
        previous: str | None,
        max_seen: datetime | None,
        *,
        now: datetime | None = None,
    ) -> str:
        """次のカーソルを組み立てる。**必ず値を返す（空バッチでも前進する）。**

        取得したイベントの最大時刻があればそれを、無ければ前回のカーソルを、
        それも無ければ現在時刻を使う。
        """
        if max_seen is not None:
            return max_seen.isoformat()
        if previous:
            return previous
        return (now or now_utc()).isoformat()
