<?php

namespace App\Console\Commands;

use App\Models\Supplier;
use Illuminate\Console\Command;
use Illuminate\Support\Str;

class AddSupplier extends Command
{
    protected $signature = 'hub:supplier:add
        {name : Supplier name}
        {--code= : PromoStandards company code, to attach imported endpoints}
        {--account= : Our account number with the supplier}
        {--username= : PromoStandards username (prompted if omitted)}';

    protected $description = 'Create a supplier profile and store its credentials in the vault';

    public function handle(): int
    {
        $name = (string) $this->argument('name');
        $code = $this->option('code');

        // If the directory import already created this supplier, attach to it instead of duplicating.
        $supplier = $code ? Supplier::where('promostandards_code', $code)->first() : null;
        $supplier ??= new Supplier(['slug' => $this->uniqueSlug($name), 'type' => 'promostandards', 'status' => Supplier::STATUS_DRAFT]);

        $supplier->fill([
            'name' => $name,
            'promostandards_code' => $code ?: $supplier->promostandards_code,
            'account_number' => $this->option('account') ?: $supplier->account_number,
            'is_active' => true,
        ])->save();

        $username = $this->option('username') ?: $this->ask('PromoStandards username');
        // secret() does not echo and keeps the password out of shell history and process lists.
        $password = $this->secret('PromoStandards password');

        if (! $username || ! $password) {
            $this->error('Username and password are required.');

            return self::FAILURE;
        }

        $supplier->credentials()->updateOrCreate([], [
            'username' => $username,
            'password' => $password,
            'rotated_at' => now(),
        ]);

        $count = $supplier->endpoints()->count();
        $this->info("Supplier '{$supplier->name}' saved as {$supplier->slug} with {$count} endpoint(s).");
        if ($count === 0) {
            $this->warn('No endpoints yet. Run hub:directory:import --code=... first, or add endpoints by hand.');
        }

        return self::SUCCESS;
    }

    private function uniqueSlug(string $name): string
    {
        $base = Str::slug($name) ?: 'supplier';
        $slug = $base;
        for ($i = 2; Supplier::where('slug', $slug)->exists(); $i++) {
            $slug = "{$base}-{$i}";
        }

        return $slug;
    }
}
