# 商业域账目核对清单（只读盘点 · 生成于 P1-2/P1-5 修复前）

## A. attempt 无预留记录（批准事务不完整或历史数据）
- （无）

## B. 预留仍 reserved 但 attempt 已终态（未释放/未结算的悬挂预留）
- {'reservation_id': 1, 'amount': Decimal('0.13500000'), 'attempt_id': 1, 'status': 'REVIEW_APPROVED'}
- {'reservation_id': 2, 'amount': Decimal('0.15000000'), 'attempt_id': 2, 'status': 'REVIEW_REJECTED'}
- {'reservation_id': 3, 'amount': Decimal('0.07500000'), 'attempt_id': 3, 'status': 'REVIEW_APPROVED'}
- {'reservation_id': 4, 'amount': Decimal('0.09000000'), 'attempt_id': 4, 'status': 'REVIEW_APPROVED'}
- {'reservation_id': 5, 'amount': Decimal('0.13500000'), 'attempt_id': 5, 'status': 'REVIEW_APPROVED'}
- {'reservation_id': 6, 'amount': Decimal('0.15000000'), 'attempt_id': 6, 'status': 'REVIEW_APPROVED'}
- {'reservation_id': 7, 'amount': Decimal('0.07500000'), 'attempt_id': 7, 'status': 'REVIEW_REJECTED'}
- {'reservation_id': 8, 'amount': Decimal('0.09000000'), 'attempt_id': 8, 'status': 'REVIEW_APPROVED'}
- {'reservation_id': 9, 'amount': Decimal('0.07500000'), 'attempt_id': 9, 'status': 'REVIEW_APPROVED'}
- {'reservation_id': 10, 'amount': Decimal('0.13500000'), 'attempt_id': 10, 'status': 'REVIEW_APPROVED'}
- {'reservation_id': 11, 'amount': Decimal('0.15000000'), 'attempt_id': 11, 'status': 'REVIEW_APPROVED'}
- {'reservation_id': 12, 'amount': Decimal('0.07500000'), 'attempt_id': 12, 'status': 'REVIEW_APPROVED'}
- {'reservation_id': 13, 'amount': Decimal('0.09000000'), 'attempt_id': 13, 'status': 'REVIEW_APPROVED'}

## C. SUBMIT_UNKNOWN 的预留（保留正确，列出待人工对账）
- （无）

## D. 同一 attempt 多条账本行（历史重复入账，修复前缺陷特征）
- （无）

## E. GENERATED 但无账本行（入账缺失）
- （无）

## F. 预算池余额快照（reserved/settled 与明细合计的差异）
- {'id': 1, 'scope': 'mock', 'total_amount': Decimal('50.00000000'), 'reserved_amount': Decimal('1.42500000'), 'settled_amount': Decimal('0E-8'), 'reserved_detail': Decimal('1.42500000'), 'settled_detail': Decimal('0')}
