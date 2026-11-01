# Plant capacity check

The inventory model assumes unlimited supply. `capacity` checks that assumption against
each supply plant's daily production limit (kg/day) in `config/plant_capacity.json`.

1. The scenario is run as usual, and each lane's mean daily order quantity over the
   validation trials is its request on its plant.
2. Each lane first receives up to 100 kg/day, largest request first, so the biggest
   customers are covered when capacity is short.
3. Capacity left over is shared in proportion to each lane's unmet request. When
   requests exceed capacity, all capacity is allocated.
4. `capacity.csv` lists each lane's request, allocation and shortfall.

Capacities must be non-negative numbers. Every site in the lane file must belong to a
plant; sites and plants are mapped in `meridian.capacity`.

```bash
python -m meridian capacity --data data/synthetic_sites.csv --config config/quickstart.json \
    --capacity config/plant_capacity.json --output results/capacity
```
