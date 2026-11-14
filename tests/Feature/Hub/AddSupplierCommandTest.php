<?php

namespace Tests\Feature\Hub;

use App\Models\Supplier;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class AddSupplierCommandTest extends TestCase
{
    use RefreshDatabase;

    public function test_add_stores_encrypted_credentials_and_unique_slug(): void
    {
        $this->artisan('hub:supplier:add', ['name' => 'Acme Promo', '--username' => 'u1'])
            ->expectsQuestion('PromoStandards password', 'p1')->assertSuccessful();
        $this->artisan('hub:supplier:add', ['name' => 'Acme Promo', '--username' => 'u2'])
            ->expectsQuestion('PromoStandards password', 'p2')->assertSuccessful();

        $this->assertSame(['acme-promo', 'acme-promo-2'], Supplier::orderBy('id')->pluck('slug')->all());
        $this->assertSame('p1', Supplier::first()->credentials->password);
    }

    public function test_add_attaches_to_a_directory_imported_supplier(): void
    {
        $existing = Supplier::create(['name' => 'Acme', 'slug' => 'acme', 'promostandards_code' => 'ACME', 'is_active' => false]);

        $this->artisan('hub:supplier:add', ['name' => 'Acme Promo', '--code' => 'ACME', '--username' => 'u'])
            ->expectsQuestion('PromoStandards password', 'p')->assertSuccessful();

        $this->assertSame(1, Supplier::count());
        $this->assertTrue($existing->fresh()->is_active);
        $this->assertNotNull($existing->fresh()->credentials);
    }
}
