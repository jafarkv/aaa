<?php

namespace Tests\Feature\Hub;

use App\Models\Supplier;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class CredentialVaultTest extends TestCase
{
    use RefreshDatabase;

    private function supplier(): Supplier
    {
        $supplier = Supplier::create(['name' => 'Acme Promo', 'slug' => 'acme-promo']);
        $supplier->credentials()->create(['username' => 'acme-user', 'password' => 'S3cret!pass']);

        return $supplier;
    }

    public function test_credentials_are_encrypted_in_the_database(): void
    {
        $this->supplier();

        $row = DB::table('supplier_credentials')->first();

        $this->assertStringNotContainsString('acme-user', $row->username);
        $this->assertStringNotContainsString('S3cret!pass', $row->password);
    }

    public function test_credentials_decrypt_when_read_through_the_model(): void
    {
        $credentials = $this->supplier()->fresh()->credentials;

        $this->assertSame('acme-user', $credentials->username);
        $this->assertSame('S3cret!pass', $credentials->password);
    }

    public function test_credentials_never_appear_in_array_or_json_output(): void
    {
        $credentials = $this->supplier()->fresh()->credentials;

        $this->assertArrayNotHasKey('password', $credentials->toArray());
        $this->assertArrayNotHasKey('username', $credentials->toArray());
        $this->assertStringNotContainsString('S3cret!pass', $credentials->toJson());
    }

    public function test_suppliers_are_deactivated_never_deleted(): void
    {
        $supplier = $this->supplier();
        $supplier->deactivate();

        $this->assertDatabaseHas('suppliers', ['slug' => 'acme-promo', 'is_active' => false, 'status' => 'paused']);
        $this->assertNotNull($supplier->fresh()->deactivated_at);
    }
}
