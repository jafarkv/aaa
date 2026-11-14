<?php

namespace App\Console\Commands;

use App\Models\Supplier;
use App\PromoStandards\ConnectionTester;
use Illuminate\Console\Command;
use RuntimeException;

class TestSupplier extends Command
{
    protected $signature = 'hub:supplier:test {slug : Supplier slug}';

    protected $description = 'Run a safe read-only test call against each enabled service of a supplier';

    public function handle(ConnectionTester $tester): int
    {
        $supplier = Supplier::where('slug', $this->argument('slug'))->first();
        if (! $supplier) {
            $this->error('Unknown supplier slug.');

            return self::FAILURE;
        }

        try {
            $results = $tester->test($supplier);
        } catch (RuntimeException $e) {
            $this->error($e->getMessage());

            return self::FAILURE;
        }

        if ($results === []) {
            $this->warn('Supplier has no enabled endpoints to test.');

            return self::FAILURE;
        }

        $this->table(
            ['Service', 'Result', 'Detail'],
            collect($results)->map(fn ($r, $service) => [$service, $r['status'], $r['message']])->values()->all(),
        );

        if ($supplier->status === Supplier::STATUS_DRAFT) {
            $supplier->update(['status' => Supplier::STATUS_TESTING]);
        }

        $failed = collect($results)->contains(fn ($r) => $r['status'] === 'failed');

        return $failed ? self::FAILURE : self::SUCCESS;
    }
}
