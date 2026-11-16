<?php

namespace Tests\Feature\Hub;

use App\Models\Supplier;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class SetSupplierEndpointCommandTest extends TestCase
{
    use RefreshDatabase;

    private function supplier(): Supplier
    {
        return Supplier::create(['name' => 'HIT Promotional Products', 'slug' => 'hit-promo']);
    }

    public function test_sets_a_manual_endpoint_with_the_default_version(): void
    {
        $this->supplier();

        $this->artisan('hub:supplier:endpoint', ['slug' => 'hit-promo', 'service' => 'inventory', 'url' => 'https://hit.test/inv'])
            ->assertSuccessful();

        $this->assertDatabaseHas('supplier_endpoints', [
            'service' => 'inventory', 'version' => '2.0.0', 'url' => 'https://hit.test/inv', 'source' => 'manual', 'is_enabled' => true,
        ]);
    }

    public function test_running_twice_updates_instead_of_duplicating(): void
    {
        $supplier = $this->supplier();

        $this->artisan('hub:supplier:endpoint', ['slug' => 'hit-promo', 'service' => 'ProductData', 'url' => 'https://hit.test/a']);
        $this->artisan('hub:supplier:endpoint', ['slug' => 'hit-promo', 'service' => 'product_data', 'url' => 'https://hit.test/b']);

        $this->assertSame(1, $supplier->endpoints()->count());
        $this->assertDatabaseHas('supplier_endpoints', ['url' => 'https://hit.test/b']);
    }

    public function test_plain_http_is_refused_because_credentials_travel_in_the_body(): void
    {
        $supplier = $this->supplier();

        $this->artisan('hub:supplier:endpoint', ['slug' => 'hit-promo', 'service' => 'inventory', 'url' => 'http://hit.test/inv'])
            ->assertFailed();

        $this->assertSame(0, $supplier->endpoints()->count());
    }

    public function test_unknown_service_and_supplier_fail_cleanly(): void
    {
        $this->supplier();

        $this->artisan('hub:supplier:endpoint', ['slug' => 'hit-promo', 'service' => 'nonsense', 'url' => 'https://x.test'])->assertFailed();
        $this->artisan('hub:supplier:endpoint', ['slug' => 'nope', 'service' => 'inventory', 'url' => 'https://x.test'])->assertFailed();
    }
}
