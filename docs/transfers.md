# Stock transfers with lane priorities

At the end of a scenario some product-locations hold more stock than they need to cover
their lead time, while others of the same product are short. `meridian transfers`
suggests moving surplus between sites to close those gaps. When there is not enough
surplus for everyone, lanes with a higher **priority weight** receive a larger share.

```bash
python -m meridian transfers --data data/synthetic_sites.csv --config config/baseline.json \
    --priorities priorities.json --output results/transfers
```

## Priorities

Give priority weights as a JSON object of lane to weight:

```json
{
  "Harbor:oxygen": 3,
  "Meadow:oxygen": 1
}
```

- Weights are positive numbers up to 100. Lanes not listed have weight 1.
- Weights are relative: a lane with weight 3 receives three times the share of a lane with
  weight 1 when surplus is short. With no priorities file, surplus is shared equally.
- Typical uses: hospitals and food producers ahead of general industry, or contract
  customers with penalties ahead of spot customers.

## Method

1. **Positions.** For each lane, the mean ending inventory (minus ending backlog) over the
   validation replications, less mean demand over its lead time. Positive is surplus;
   negative is a shortfall.
2. **Products.** Transfers only move a product between lanes of that product.
3. **Shares.** Each short lane's share is its weight divided by the total weight of the
   short lanes, so shares add up to 1. A lane receives its share of the product's total
   surplus, but never more than its shortfall.
4. **Order.** Short lanes are served in priority order, then largest shortfall first.
   Each takes stock from the surplus lanes with the most to spare.

## Output

`transfers.csv` lists each suggested move: product, from lane, to lane and quantity (kg).
The command also prints, for each short lane, its priority, shortfall, the quantity it
receives and what is still missing.

## Example

Oxygen surplus is 1,000 kg. Harbor (weight 3) is 900 kg short and Meadow (weight 1) is
600 kg short. Shares are 3/4 and 1/4, so Harbor receives 750 kg and Meadow 250 kg; both
remain partly short, Harbor by 150 kg and Meadow by 350 kg.

## Limits

- Transfers are suggestions at the end of the horizon; they are not simulated, and
  transport time and cost are not included.
- Positions use mean outcomes; individual replications vary.
